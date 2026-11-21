"""Oracle model client: always emits a case's gold tool call.

Running the eval with the oracle checks the eval set itself (every gold plan resolves, executes,
and ends in the expected response kind) and the scoring code (it should score 100%).
"""

from __future__ import annotations

import json
from typing import Any

from agent.decoding import DecodingProfile
from agent.model_clients.base import ModelOutput
from evaluation.cases import EvalCase


class OracleModelClient:
    model_id = "oracle"

    def __init__(self, case: EvalCase):
        call = dict(case.gold_call)
        if call["tool"] == "respond":
            call.setdefault("text", f"[{call['kind']}] oracle reply")
        self._planner_text = json.dumps({"call": call})

    def complete(
        self,
        messages: list[dict[str, str]],
        profile: DecodingProfile,
        json_schema: dict[str, Any] | None = None,
    ) -> ModelOutput:
        # Planning steps get the gold call; answer steps get no text, so the agent uses its
        # deterministic template (the oracle is not a test of prose).
        text = self._planner_text if profile.step == "plan" else ""
        return ModelOutput(text=text, model_id=self.model_id, latency_ms=0.0)
