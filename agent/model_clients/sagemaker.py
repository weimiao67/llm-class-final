"""SageMaker real-time endpoint client for the HF TGI container (Messages API), as used in A7."""

from __future__ import annotations

import json
import time
from typing import Any

import boto3
from botocore.config import Config

from agent.decoding import DecodingProfile, tgi_parameters
from agent.model_clients.base import ModelOutput

DEFAULT_TIMEOUT_S = 30


class SageMakerModelClient:
    def __init__(
        self,
        endpoint_name: str,
        model_id: str | None = None,
        region: str = "us-east-2",
        runtime_client: Any | None = None,
        sagemaker_client: Any | None = None,
        timeout_s: int = DEFAULT_TIMEOUT_S,
    ):
        self.endpoint_name = endpoint_name
        self.model_id = model_id or endpoint_name
        config = Config(
            read_timeout=timeout_s,
            connect_timeout=5,
            retries={"max_attempts": 2, "mode": "standard"},  # one retry on throttling/5xx
        )
        self._runtime = runtime_client or boto3.client(
            "sagemaker-runtime", region_name=region, config=config
        )
        self._sagemaker = sagemaker_client or boto3.client("sagemaker", region_name=region)

    def complete(
        self,
        messages: list[dict[str, str]],
        profile: DecodingProfile,
        json_schema: dict[str, Any] | None = None,
    ) -> ModelOutput:
        body = {"messages": messages, **tgi_parameters(profile, json_schema)}
        start = time.perf_counter()
        response = self._runtime.invoke_endpoint(
            EndpointName=self.endpoint_name,
            ContentType="application/json",
            Accept="application/json",
            Body=json.dumps(body),
        )
        reply = json.loads(response["Body"].read())
        latency_ms = (time.perf_counter() - start) * 1000
        usage = reply.get("usage") or {}
        return ModelOutput(
            text=reply["choices"][0]["message"]["content"] or "",
            model_id=self.model_id,
            latency_ms=latency_ms,
            usage={k: usage[k] for k in ("prompt_tokens", "completion_tokens") if k in usage},
        )

    def health(self) -> dict[str, Any]:
        status = self._sagemaker.describe_endpoint(EndpointName=self.endpoint_name)
        return {"endpoint": self.endpoint_name, "status": status["EndpointStatus"]}
