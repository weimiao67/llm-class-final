"""Deploy, inspect, or delete a SageMaker real-time TGI endpoint for the planner model.

Adapted from assignment A7 (same TGI container and Messages API). Two model sources:
  * a Hugging Face Hub model, e.g. the Step 2 baseline (needs HF_TOKEN for gated Llama models)
  * merged weights in S3 (model.tar.gz), e.g. the Step 3 LoRA model

Run in a SageMaker Studio terminal from the repo root (Studio has the AWS credentials and the
execution role):
    export HF_TOKEN=hf_...                         # gated models only
    python scripts/deploy_endpoint.py              # Llama-3.2-3B-Instruct baseline, ~10 min
    python scripts/deploy_endpoint.py --status
    python scripts/deploy_endpoint.py --delete     # stop billing: ALWAYS run after a session

    python scripts/deploy_endpoint.py --name final-wm-lora-v1 \
        --model-data s3://<bucket>/final-wm/models/<run>/model.tar.gz

The endpoint bills by the hour (ml.g5.2xlarge is about $1.5/h) until --delete.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

REGION = "us-east-2"
DEFAULT_HF_MODEL = "meta-llama/Llama-3.2-3B-Instruct"
DEFAULT_NAME = "final-wm-llama32-3b-base"
DEFAULT_INSTANCE = "ml.g5.2xlarge"  # reached InService in A7; g5.xlarge did not
TGI_VERSION = "3.3.6"  # newest huggingface-llm image known to work (A7)
TAGS = [{"Key": "project", "Value": "llm-final"}, {"Key": "owner", "Value": "wmiao"}]

# Token budget: planner system prompt (~1k tokens) + up to 6 history messages + tool results,
# or the answer prompt with a compact summary, stays under 3072 input tokens; replies are
# capped at 256 (plans) / 200 (answers) new tokens. A7's 1024-token input limit is too small.
TGI_LIMITS = {
    "MAX_INPUT_TOKENS": "3072",
    "MAX_TOTAL_TOKENS": "4096",
    "MAX_BATCH_PREFILL_TOKENS": "4096",
}


def container_env(hf_model_id: str | None, model_data: str | None, hf_token: str | None) -> dict:
    """TGI environment for one model source (exactly one of hf_model_id / model_data)."""
    if bool(hf_model_id) == bool(model_data):
        raise ValueError("give exactly one of hf_model_id or model_data")
    env = {
        "HF_MODEL_ID": hf_model_id or "/opt/ml/model",  # SageMaker unpacks model_data there
        "MESSAGES_API_ENABLED": "true",  # OpenAI-style {"messages": [...]} on /invocations
        "DTYPE": "bfloat16",
        "SM_NUM_GPUS": "1",
        **TGI_LIMITS,
    }
    if hf_model_id:
        if not hf_token:
            raise ValueError("HF_TOKEN is required to download a gated Hub model")
        env["HF_TOKEN"] = hf_token
    return env


def endpoint_specs(
    name: str, image: str, role: str, instance_type: str, env: dict, model_data: str | None
) -> dict[str, dict[str, Any]]:
    container: dict[str, Any] = {"Image": image, "Environment": env}
    if model_data:
        container["ModelDataUrl"] = model_data
    return {
        "model": {
            "ModelName": name,
            "ExecutionRoleArn": role,
            "PrimaryContainer": container,
            "Tags": TAGS,
        },
        "config": {
            "EndpointConfigName": name,
            "ProductionVariants": [
                {
                    "VariantName": "AllTraffic",
                    "ModelName": name,
                    "InstanceType": instance_type,
                    "InitialInstanceCount": 1,
                    "ModelDataDownloadTimeoutInSeconds": 1200,
                    "ContainerStartupHealthCheckTimeoutInSeconds": 900,
                }
            ],
            "Tags": TAGS,
        },
        "endpoint": {"EndpointName": name, "EndpointConfigName": name, "Tags": TAGS},
    }


# ---- SageMaker SDK helpers (imported lazily: only needed in Studio) --------------------------


def tgi_image_uri(instance_type: str, version: str) -> str:
    try:  # sagemaker SDK v3 (what A7 used)
        from sagemaker.core import image_uris
    except ImportError:  # sagemaker SDK v2
        from sagemaker import image_uris
    return image_uris.retrieve(
        framework="huggingface-llm",
        region=REGION,
        version=version,
        instance_type=instance_type,
        image_scope="inference",
    )


def execution_role() -> str:
    try:
        from sagemaker.core.helper.session_helper import get_execution_role
    except ImportError:
        from sagemaker import get_execution_role
    return get_execution_role()


# ---- actions ---------------------------------------------------------------------------------


def deploy(sm, specs: dict[str, dict[str, Any]], wait: bool) -> None:
    name = specs["endpoint"]["EndpointName"]
    sm.create_model(**specs["model"])
    sm.create_endpoint_config(**specs["config"])
    sm.create_endpoint(**specs["endpoint"])
    print(f"Creating endpoint {name} — billing starts now (~10 min until InService).")
    if wait:
        sm.get_waiter("endpoint_in_service").wait(
            EndpointName=name, WaiterConfig={"Delay": 30, "MaxAttempts": 60}
        )
        print(f"{name} is InService. Delete it when done: python {sys.argv[0]} --delete")


def status(sm, name: str) -> None:
    try:
        info = sm.describe_endpoint(EndpointName=name)
    except sm.exceptions.ClientError as error:
        print(f"{name}: {error.response['Error']['Message']}")
        return
    print(
        f"{name}: {info['EndpointStatus']}"
        + (f" — {info['FailureReason']}" if info.get("FailureReason") else "")
    )


def delete(sm, name: str) -> None:
    """Delete endpoint, endpoint config, and model; skip any that are already gone."""
    steps = (
        ("endpoint", sm.delete_endpoint, {"EndpointName": name}),
        ("endpoint config", sm.delete_endpoint_config, {"EndpointConfigName": name}),
        ("model", sm.delete_model, {"ModelName": name}),
    )
    for label, call, kwargs in steps:
        try:
            call(**kwargs)
            print(f"Deleted {label} {name}")
        except sm.exceptions.ClientError as error:
            print(f"Skipped {label}: {error.response['Error']['Message']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--delete", action="store_true", help="tear down (stops billing)")
    action.add_argument("--status", action="store_true", help="show endpoint status")
    parser.add_argument("--name", default=DEFAULT_NAME, help=f"default: {DEFAULT_NAME}")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--hf-model-id", help=f"Hub model (default: {DEFAULT_HF_MODEL})")
    source.add_argument("--model-data", help="s3://.../model.tar.gz with merged weights")
    parser.add_argument("--instance-type", default=DEFAULT_INSTANCE)
    parser.add_argument("--tgi-version", default=TGI_VERSION)
    parser.add_argument("--image-uri", help="override the TGI image (skips the SDK lookup)")
    parser.add_argument("--role", help="execution role ARN (default: Studio's)")
    parser.add_argument("--no-wait", action="store_true", help="return before InService")
    args = parser.parse_args(argv)

    import boto3

    sm = boto3.client("sagemaker", region_name=REGION)
    if args.delete:
        delete(sm, args.name)
        return 0
    if args.status:
        status(sm, args.name)
        return 0

    hf_model = None if args.model_data else (args.hf_model_id or DEFAULT_HF_MODEL)
    env = container_env(hf_model, args.model_data, os.environ.get("HF_TOKEN"))
    image = args.image_uri or tgi_image_uri(args.instance_type, args.tgi_version)
    specs = endpoint_specs(
        args.name, image, args.role or execution_role(), args.instance_type, env, args.model_data
    )
    deploy(sm, specs, wait=not args.no_wait)
    return 0


if __name__ == "__main__":
    sys.exit(main())
