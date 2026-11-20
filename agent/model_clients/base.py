"""Model-client interface shared by the stub, SageMaker, and batch-eval backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from agent.decoding import DecodingProfile


@dataclass
class ModelOutput:
    text: str
    model_id: str
    latency_ms: float
    usage: dict[str, int] = field(default_factory=dict)


class ModelClient(Protocol):
    model_id: str

    def complete(
        self,
        messages: list[dict[str, str]],
        profile: DecodingProfile,
        json_schema: dict[str, Any] | None = None,
    ) -> ModelOutput: ...
