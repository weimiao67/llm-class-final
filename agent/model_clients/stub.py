"""Deterministic stub model for offline development, tests, and CI.

Planning steps return canned tool calls chosen by keyword rules on the latest user message; answer
steps return a short text built from the tool summary in the last message.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from agent.decoding import DecodingProfile
from agent.model_clients.base import ModelOutput

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
    calls: list[dict[str, Any]] = field(default_factory=list)

    def complete(
        self,
        messages: list[dict[str, str]],
        profile: DecodingProfile,
        json_schema: dict[str, Any] | None = None,
    ) -> ModelOutput:
        start = time.perf_counter()
        self.calls.append({"messages": messages, "profile": profile.name})
        if profile.constrained:
            question = next(m["content"] for m in reversed(messages) if m["role"] == "user")
            payload = next(
                (out for pattern, out in self.rules if re.search(pattern, question, re.I)),
                FALLBACK,
            )
            text = json.dumps(payload)
        else:
            text = f"Based on the tool results: {messages[-1]['content'][:300]}"
        return ModelOutput(
            text=text, model_id=self.model_id, latency_ms=(time.perf_counter() - start) * 1000
        )


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
            r"what is zori|what is zhvi",
            {
                "call": {
                    "tool": "search_knowledge",
                    "query": "ZORI methodology smoothing",
                    "top_k": 3,
                }
            },
        ),
    ]
