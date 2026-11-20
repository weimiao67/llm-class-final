"""Versioned tool schemas.

The JSON Schema of :class:`ToolCall` is what the model sees in its prompt and what constrained
decoding enforces. Structural rules live here; data-dependent rules (does the city exist, is the
period covered) live in :mod:`tools.validator`.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TOOL_PROTOCOL_VERSION = 1

Metric = Literal["zhvi", "zori"]
Operation = Literal["series", "change", "yoy_change", "extrema", "rank", "aggregate", "coverage"]
Month = Annotated[
    str, Field(pattern=r"^(19|20)\d{2}-(0[1-9]|1[0-2])$", description="YYYY-MM, 1900-2099")
]
StateCode = Annotated[str, Field(pattern=r"^[A-Z]{2}$", description="Two-letter state code")]

MAX_CITIES = 20
MAX_LIMIT = 50


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CityRef(_Strict):
    city: Annotated[str, Field(min_length=1, max_length=80)]
    state: StateCode | None = None
    county: Annotated[str, Field(max_length=80)] | None = None


class AnalysisPlan(_Strict):
    metric: Metric
    cities: Annotated[list[CityRef], Field(max_length=MAX_CITIES)] = []
    state_filter: StateCode | None = None
    start_month: Month | None = None
    end_month: Month | None = None
    operation: Operation
    aggregate: Literal["avg", "median", "min", "max", "count"] | None = None
    rank_by: Literal["value", "change", "pct_change"] | None = None
    order: Literal["desc", "asc"] = "desc"
    limit: Annotated[int, Field(ge=1, le=MAX_LIMIT)] = 10

    @model_validator(mode="after")
    def _structural_rules(self) -> AnalysisPlan:
        if bool(self.cities) == bool(self.state_filter):
            raise ValueError("set exactly one of 'cities' or 'state_filter'")
        if (self.operation == "aggregate") != (self.aggregate is not None):
            raise ValueError("'aggregate' is required for, and only for, operation 'aggregate'")
        if (self.operation == "rank") != (self.rank_by is not None):
            raise ValueError("'rank_by' is required for, and only for, operation 'rank'")
        if self.operation == "series" and self.state_filter:
            raise ValueError(
                "operation 'series' needs explicit 'cities'; use 'rank' or 'aggregate' for a state"
            )
        if self.start_month and self.end_month and self.start_month > self.end_month:
            raise ValueError("'start_month' must not be after 'end_month'")
        return self


class AnalyzeCall(_Strict):
    tool: Literal["analyze"]
    plan: AnalysisPlan


class SearchKnowledgeCall(_Strict):
    tool: Literal["search_knowledge"]
    query: Annotated[str, Field(min_length=1, max_length=300)]
    top_k: Annotated[int, Field(ge=1, le=5)] = 3


class RespondCall(_Strict):
    tool: Literal["respond"]
    kind: Literal["answer", "clarify", "unsupported", "out_of_scope"]
    text: Annotated[str, Field(min_length=1, max_length=2000)]


class ToolCall(BaseModel):
    """Envelope the model must emit on every planning step."""

    call: Annotated[AnalyzeCall | SearchKnowledgeCall | RespondCall, Field(discriminator="tool")]


# ---- Results returned by tools (never produced by the model) --------------------------------

ErrorKind = Literal[
    "invalid_plan",
    "ambiguous_city",
    "city_not_found",
    "no_data",
    "capability_not_implemented",
]


class ToolError(BaseModel):
    kind: ErrorKind
    message: str
    details: dict[str, Any] = {}

    @property
    def retryable(self) -> bool:
        return self.kind == "invalid_plan"


class ResolvedRegion(BaseModel):
    region_id: str
    city: str
    state: str
    county: str | None


class QueryArtifact(BaseModel):
    operation: Operation
    metric: Metric
    rows: list[dict[str, Any]]
    summary: dict[str, Any]
    regions: list[ResolvedRegion]
    period: dict[str, date | None]
    sql: dict[str, Any]
    chart: dict[str, Any] | None = None
    warnings: list[str] = []
    dataset_version: str


def tool_call_json_schema() -> dict[str, Any]:
    """JSON Schema for prompts and grammar-constrained decoding."""
    return ToolCall.model_json_schema()
