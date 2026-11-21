"""Evaluation-case schema and loader.

A case is one user turn (optionally with prior history and conversation state) plus the gold
first tool call and the response kind the system should end with. ``alt_calls`` lists other
calls that are equally correct (e.g. ``change`` vs ``series`` for "compare A and B").
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from tools.schemas import AnalysisPlan, ConversationState

Family = Literal[
    "single_city",
    "extrema",
    "multi_city",
    "aggregate",
    "coverage",
    "methodology",
    "follow_up",
    "ambiguous",
    "boundary",
    "injection",
]
ExpectedResponse = Literal["answer", "clarify", "no_data", "unsupported", "out_of_scope"]


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    family: Family
    question: str
    history: list[dict[str, str]] = []
    state: ConversationState = ConversationState()
    gold_call: dict[str, Any]
    alt_calls: list[dict[str, Any]] = []
    expected_response: ExpectedResponse
    notes: str = ""

    @model_validator(mode="after")
    def _check_calls(self) -> EvalCase:
        for call in [self.gold_call, *self.alt_calls]:
            tool = call.get("tool")
            if tool == "analyze":
                AnalysisPlan.model_validate(call["plan"])
            elif tool == "respond":
                if call.get("kind") != self.expected_response:
                    raise ValueError(f"{self.id}: respond kind must equal expected_response")
            elif tool != "search_knowledge":
                raise ValueError(f"{self.id}: unknown tool {tool!r}")
        if any(c["tool"] != self.gold_call["tool"] for c in self.alt_calls):
            raise ValueError(f"{self.id}: alt_calls must use the same tool as gold_call")
        return self

    @property
    def expected_tool(self) -> str:
        return self.gold_call["tool"]

    def acceptable_plans(self) -> list[dict[str, Any]]:
        return [c["plan"] for c in [self.gold_call, *self.alt_calls] if c["tool"] == "analyze"]


def load_cases(path: Path | str) -> list[EvalCase]:
    cases = []
    for lineno, line in enumerate(Path(path).read_text().splitlines(), start=1):
        if line.strip():
            try:
                cases.append(EvalCase.model_validate(json.loads(line)))
            except Exception as exc:
                raise ValueError(f"{path}:{lineno}: {exc}") from exc
    ids = [c.id for c in cases]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate case ids: {sorted(dupes)}")
    return cases
