"""Deterministic stub model for offline development, tests, and CI.

Planning steps return canned tool calls chosen by keyword rules on the latest user message; answer
steps return a short text built from the tool summary in the last message.
"""

from __future__ import annotations

import json
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from agent.decoding import DecodingProfile
from agent.model_clients.base import ModelOutput

STUB_CALL_LOG = 50

FALLBACK = {
    "call": {
        "tool": "respond",
        "kind": "unsupported",
        "text": "The stub model has no rule for this question.",
    }
}


@dataclass
class StubModelClient:
    """``rules`` maps a case-insensitive regex to the tool-call JSON to return."""

    rules: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    model_id: str = "stub"
    # Bounded: the stub also backs long-running local API servers.
    calls: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=STUB_CALL_LOG))

    def complete(
        self,
        messages: list[dict[str, str]],
        profile: DecodingProfile,
        json_schema: dict[str, Any] | None = None,
    ) -> ModelOutput:
        start = time.perf_counter()
        self.calls.append({"messages": messages, "profile": profile.name})
        if profile.step == "plan":
            user_messages = [m["content"] for m in messages if m["role"] == "user"]
            # Skip tool-result messages, but a user may type that prefix themselves.
            question = next(
                (c for c in reversed(user_messages) if not c.startswith("TOOL RESULT:")),
                user_messages[-1] if user_messages else "",
            )
            payload = next(
                (out for pattern, out in self.rules if re.search(pattern, question, re.I)),
                FALLBACK,
            )
            text = json.dumps(payload)
        else:
            # No answer text: the agent falls back to its deterministic template answer.
            text = ""
        return ModelOutput(
            text=text, model_id=self.model_id, latency_ms=(time.perf_counter() - start) * 1000
        )


@dataclass
class ScriptedModelClient:
    """Returns ``outputs`` in order, one per call; for testing exact agent-loop behavior."""

    outputs: list[str | dict[str, Any]]
    model_id: str = "scripted"
    calls: list[dict[str, Any]] = field(default_factory=list)

    def complete(
        self,
        messages: list[dict[str, str]],
        profile: DecodingProfile,
        json_schema: dict[str, Any] | None = None,
    ) -> ModelOutput:
        self.calls.append(
            {"messages": messages, "profile": profile.name, "schema": json_schema is not None}
        )
        if len(self.calls) > len(self.outputs):
            raise AssertionError(f"unexpected model call #{len(self.calls)} ({profile.name})")
        out = self.outputs[len(self.calls) - 1]
        text = out if isinstance(out, str) else json.dumps(out)
        return ModelOutput(text=text, model_id=self.model_id, latency_ms=1.0)


def demo_rules() -> list[tuple[str, dict[str, Any]]]:
    """Rules covering the demo questions in design doc §18.2. First match wins, so the
    out-of-scope (forecast) rule comes before any city-specific analyze rule."""

    def analyze(**plan: Any) -> dict[str, Any]:
        return {"call": {"tool": "analyze", "plan": plan}}

    return [
        (
            r"will .* (rent|value).* next year|forecast|predict",
            {
                "call": {
                    "tool": "respond",
                    "kind": "out_of_scope",
                    "text": "I can't forecast. I can show historical rent changes instead.",
                }
            },
        ),
        (
            r"mead.*highest",
            analyze(
                metric="zhvi",
                cities=[{"city": "Mead", "state": "CO"}],
                start_month="2025-01",
                end_month="2025-12",
                operation="extrema",
            ),
        ),
        (
            r"rank colorado",
            analyze(
                metric="zhvi",
                state_filter="CO",
                start_month="2025-01",
                end_month="2025-12",
                operation="rank",
                rank_by="pct_change",
            ),
        ),
        (
            r"oakwood",
            analyze(
                metric="zhvi",
                cities=[{"city": "Oakwood", "state": "OH"}],
                start_month="2020-01",
                operation="change",
            ),
        ),
        (
            # The follow-up to the Colorado ranking; the real planner reads the conversation.
            r"what about rent",
            analyze(
                metric="zori",
                state_filter="CO",
                start_month="2025-01",
                end_month="2025-12",
                operation="rank",
                rank_by="pct_change",
            ),
        ),
        (
            r"what is zori",
            {"call": {"tool": "search_knowledge", "query": "ZORI smoothing", "top_k": 3}},
        ),
        (
            r"what is zhvi",
            {"call": {"tool": "search_knowledge", "query": "ZHVI definition", "top_k": 3}},
        ),
    ]
