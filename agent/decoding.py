"""Decoding profiles per agent step (design doc §10)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Step = Literal["plan", "answer"]


@dataclass(frozen=True)
class DecodingProfile:
    name: str
    step: Step  # which agent step uses it; independent of whether output is constrained
    do_sample: bool
    temperature: float | None
    top_p: float | None
    max_new_tokens: int
    repetition_penalty: float | None = None
    constrained: bool = False  # enforce the ToolCall JSON Schema via grammar decoding


PLAN = DecodingProfile(
    "plan",
    "plan",
    do_sample=False,
    temperature=None,
    top_p=None,
    max_new_tokens=256,
    constrained=True,
)
PLAN_RETRY = DecodingProfile(
    "plan_retry",
    "plan",
    do_sample=False,
    temperature=None,
    top_p=None,
    max_new_tokens=256,
    constrained=True,
)
ANSWER = DecodingProfile(
    "answer",
    "answer",
    do_sample=True,
    temperature=0.3,
    top_p=0.9,
    max_new_tokens=200,
    repetition_penalty=1.05,
)
ANSWER_GREEDY = DecodingProfile(
    "answer_greedy", "answer", do_sample=False, temperature=None, top_p=None, max_new_tokens=200
)

PROFILES = {p.name: p for p in (PLAN, PLAN_RETRY, ANSWER, ANSWER_GREEDY)}


def tgi_parameters(profile: DecodingProfile, json_schema: dict[str, Any] | None) -> dict:
    """Map a profile to TGI Messages-API request fields (verify against the pinned TGI version)."""
    params: dict[str, Any] = {"max_tokens": profile.max_new_tokens}
    if profile.do_sample:
        params["temperature"] = profile.temperature
        params["top_p"] = profile.top_p
        if profile.repetition_penalty:
            params["frequency_penalty"] = profile.repetition_penalty - 1.0
    else:
        params["temperature"] = 0.0
    if profile.constrained and json_schema is not None:
        params["response_format"] = {"type": "json_object", "value": json_schema}
    return params
