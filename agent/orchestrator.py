"""Bounded agent loop (design doc §8).

One turn: the planner model emits tool calls under constrained greedy decoding; trusted code
validates and executes them; the answer writer turns the compact result into prose; the
faithfulness check rejects answers whose numbers are not in the result.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from agent import decoding
from agent.grounding import clarification_text, template_answer, unsupported_numbers
from agent.model_clients.base import ModelClient, ModelOutput
from agent.prompts import (
    PROMPT_VERSION,
    answer_messages,
    planner_messages,
    tool_result_message,
)
from housing.db import HousingDB
from tools.knowledge import KnowledgeBase, Passage
from tools.operations import execute
from tools.schemas import (
    AnalyzeCall,
    ConversationState,
    QueryArtifact,
    RespondCall,
    SearchKnowledgeCall,
    ToolCall,
    ToolError,
    tool_call_json_schema,
)
from tools.validator import PlanValidator, ValidatedPlan, field_errors

log = logging.getLogger(__name__)

MAX_PLAN_RETRIES = 2
MAX_PLANNER_CALLS = MAX_PLAN_RETRIES + 1  # every planner call either finishes the turn or retries
MAX_HISTORY_MESSAGES = 6
# Checked before each model call. A single call is bounded separately by the client timeout, so a
# turn can overrun this by at most one call.
TURN_TIMEOUT_S = 60.0

ResponseKind = Literal["answer", "clarify", "unsupported", "out_of_scope", "no_data", "error"]
AnswerSource = Literal["model", "model_regenerated", "template", "system"]

SAFE_RESPOND_TEXT = {
    "clarify": "Could you clarify which city, metric, or period you mean?",
    "unsupported": "The database can't answer that question with its available fields and "
    "operations.",
    "out_of_scope": "I can't forecast or predict. I can show historical, descriptive analysis "
    "instead.",
}


class TraceEvent(BaseModel):
    step: int
    tool: str
    status: Literal["ok", "retry", "stop", "error"]
    duration_ms: float
    detail: str | None = None


class AgentResponse(BaseModel):
    kind: ResponseKind
    answer: str
    answer_source: AnswerSource
    artifact: QueryArtifact | None = None
    plan: dict[str, Any] | None = None  # last AnalysisPlan the planner proposed this turn
    sources: list[Passage] = []
    trace: list[TraceEvent] = []
    updated_state: dict[str, Any] = {}
    warnings: list[str] = []
    model_id: str
    prompt_version: str = PROMPT_VERSION
    dataset_version: str
    latency_ms: dict[str, float] = {}


class TurnTimeout(Exception):
    """The turn's time budget ran out before the next model call."""


class _Turn:
    """Mutable bookkeeping for one turn."""

    def __init__(self, timeout_s: float) -> None:
        self.trace: list[TraceEvent] = []
        self.model_ms = 0.0
        self.tool_ms = 0.0
        self.plan: dict[str, Any] | None = None
        self.started = time.perf_counter()
        self.deadline = self.started + timeout_s

    def check_deadline(self) -> None:
        if time.perf_counter() >= self.deadline:
            raise TurnTimeout

    def event(self, step: int, tool: str, status: str, ms: float, detail: str | None = None):
        self.trace.append(
            TraceEvent(step=step, tool=tool, status=status, duration_ms=round(ms, 1), detail=detail)
        )

    def latency(self) -> dict[str, float]:
        total = (time.perf_counter() - self.started) * 1000
        return {
            "model": round(self.model_ms, 1),
            "tools": round(self.tool_ms, 1),
            "total": round(total, 1),
        }


class Agent:
    def __init__(
        self,
        db: HousingDB,
        model: ModelClient,
        knowledge: KnowledgeBase | None = None,
        validator: PlanValidator | None = None,
        turn_timeout_s: float = TURN_TIMEOUT_S,
    ):
        self.turn_timeout_s = turn_timeout_s
        self.db = db
        self.model = model
        self.knowledge = knowledge
        self.validator = validator or PlanValidator(db)
        self._schema = tool_call_json_schema()

    # ---- public --------------------------------------------------------------------------------

    def run_turn(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
        state: dict[str, Any] | None = None,
    ) -> AgentResponse:
        turn = _Turn(self.turn_timeout_s)
        try:
            return self._run(question, (history or [])[-MAX_HISTORY_MESSAGES:], state or {}, turn)
        except TurnTimeout:
            log.warning("agent turn exceeded %.0f s", self.turn_timeout_s)
            turn.event(len(turn.trace) + 1, "agent", "error", 0, "turn timeout")
            return self._response(
                turn,
                "error",
                "That took too long to answer. Please try again in a moment.",
                "system",
                state=state or {},
            )
        except Exception:  # model/endpoint/infrastructure failure: safe message, details in logs
            log.exception("agent turn failed")
            turn.event(len(turn.trace) + 1, "agent", "error", 0, "internal error")
            return self._response(
                turn,
                "error",
                "Something went wrong while answering. Please try again.",
                "system",
                state=state or {},
            )

    # ---- loop ----------------------------------------------------------------------------------

    def _run(self, question, history, state, turn: _Turn) -> AgentResponse:
        messages = planner_messages(self.db, question, history, state or None)
        retries = 0
        for step in range(1, MAX_PLANNER_CALLS + 1):
            profile = decoding.PLAN if retries == 0 else decoding.PLAN_RETRY
            out = self._complete(turn, messages, profile, self._schema)
            messages = [*messages, {"role": "assistant", "content": out.text}]

            try:
                call = ToolCall.model_validate_json(out.text).call
            except ValidationError as exc:
                retries += 1
                turn.event(step, "planner", "retry", 0, "invalid tool call")
                if retries > MAX_PLAN_RETRIES:
                    return self._give_up(turn, state)
                messages.append(
                    tool_result_message({"error": "invalid_tool_call", "errors": field_errors(exc)})
                )
                continue

            if isinstance(call, RespondCall):
                return self._respond(turn, step, call, question, state)

            if isinstance(call, SearchKnowledgeCall):
                return self._search(turn, step, call, question, state)

            if not isinstance(call, AnalyzeCall):  # unreachable unless ToolCall gains a tool
                raise TypeError(f"unhandled tool call {type(call).__name__}")
            t0 = time.perf_counter()
            turn.plan = call.plan.model_dump()
            result = self.validator.validate(call.plan)
            vplan = result if isinstance(result, ValidatedPlan) else None
            if vplan is not None:
                result = execute(vplan, self.db)
            ms = (time.perf_counter() - t0) * 1000
            turn.tool_ms += ms

            if isinstance(result, QueryArtifact):
                turn.event(
                    step, "analyze", "ok", ms, f"{result.operation}, {len(result.rows)} rows"
                )
                return self._answer_from_artifact(turn, question, result, vplan)

            err: ToolError = result
            if err.retryable:
                retries += 1
                turn.event(step, "analyze", "retry", ms, err.kind)
                if retries > MAX_PLAN_RETRIES:
                    return self._give_up(turn, state)
                messages.append(tool_result_message(err.model_dump()))
                continue

            turn.event(step, "analyze", "stop", ms, err.kind)
            if err.kind in ("ambiguous_city", "city_not_found"):
                return self._response(
                    turn, "clarify", clarification_text(err), "system", state=state
                )
            return self._response(turn, "no_data", err.message, "system", state=state)

        turn.event(MAX_PLANNER_CALLS, "agent", "stop", 0, "step limit reached")
        return self._give_up(turn, state)

    # ---- steps ---------------------------------------------------------------------------------

    def _complete(self, turn: _Turn, messages, profile, schema=None) -> ModelOutput:
        turn.check_deadline()
        out = self.model.complete(messages, profile, schema if profile.constrained else None)
        turn.model_ms += out.latency_ms
        return out

    def _respond(self, turn, step, call: RespondCall, question, state) -> AgentResponse:
        turn.event(step, "respond", "ok", 0, call.kind)
        # A direct reply has no tool evidence, so it may not contain numbers of its own.
        if unsupported_numbers(call.text, {}, question):
            return self._response(
                turn, call.kind, SAFE_RESPOND_TEXT[call.kind], "system", state=state
            )
        return self._response(turn, call.kind, call.text, "model", state=state)

    def _search(self, turn, step, call: SearchKnowledgeCall, question, state) -> AgentResponse:
        if self.knowledge is None:
            turn.event(step, "search_knowledge", "error", 0, "knowledge base unavailable")
            return self._response(
                turn,
                "error",
                "The methodology knowledge base is not available right now.",
                "system",
                state=state,
            )
        t0 = time.perf_counter()
        passages = self.knowledge.search(call.query, call.top_k)
        ms = (time.perf_counter() - t0) * 1000
        turn.tool_ms += ms
        turn.event(step, "search_knowledge", "ok", ms, f"{len(passages)} passages")
        if not passages:
            return self._response(
                turn,
                "no_data",
                "I couldn't find that in the methodology documents.",
                "system",
                state=state,
            )
        evidence = {
            "passages": [p.model_dump(include={"title", "section", "text"}) for p in passages]
        }
        fallback = f'From "{passages[0].title}": {passages[0].text[:400]}'
        text, source = self._write_answer(turn, question, evidence, fallback)
        return self._response(turn, "answer", text, source, sources=passages, state=state)

    def _answer_from_artifact(self, turn, question, art: QueryArtifact, vplan) -> AgentResponse:
        evidence = {
            "operation": art.operation,
            "metric": art.metric,
            "period": art.period,
            "summary": art.summary,
            "warnings": art.warnings,
        }
        text, source = self._write_answer(turn, question, evidence, template_answer(art))
        return self._response(
            turn,
            "answer",
            text,
            source,
            artifact=art,
            state=_state_from(vplan),
            warnings=art.warnings,
        )

    def _write_answer(self, turn, question, evidence, fallback) -> tuple[str, AnswerSource]:
        messages = answer_messages(question, evidence)
        for profile, source in (
            (decoding.ANSWER, "model"),
            (decoding.ANSWER_GREEDY, "model_regenerated"),
        ):
            text = self._complete(turn, messages, profile).text.strip()
            bad = unsupported_numbers(text, evidence, question)
            if not text:
                problem = "empty answer"
            elif bad:
                problem = f"ungrounded numbers: {', '.join(bad[:5])}"
            else:
                problem = None
            turn.event(
                len(turn.trace) + 1,
                "answer_writer",
                "retry" if problem else "ok",
                0,
                f"{profile.name}: {problem}" if problem else profile.name,
            )
            if problem is None:
                return text, source
        turn.event(len(turn.trace) + 1, "answer_writer", "ok", 0, "template fallback")
        return fallback, "template"

    # ---- helpers -------------------------------------------------------------------------------

    def _give_up(self, turn, state) -> AgentResponse:
        return self._response(
            turn,
            "error",
            "I couldn't turn that question into a valid analysis."
            " Try naming the city, metric (home values or rents), and period.",
            "system",
            state=state,
        )

    def _response(
        self,
        turn: _Turn,
        kind,
        answer,
        source,
        *,
        state,
        artifact=None,
        sources=None,
        warnings=None,
    ) -> AgentResponse:
        return AgentResponse(
            kind=kind,
            answer=answer,
            answer_source=source,
            artifact=artifact,
            plan=turn.plan,
            sources=sources or [],
            trace=turn.trace,
            updated_state=state or {},
            warnings=warnings or [],
            model_id=self.model.model_id,
            dataset_version=self.db.dataset_version,
            latency_ms=turn.latency(),
        )


def _state_from(vplan: ValidatedPlan) -> dict[str, Any]:
    """Conversation context for follow-ups, built from what was actually resolved and run."""
    plan = vplan.plan
    state = ConversationState(
        metric=plan.metric,
        cities=[{"city": r.city, "state": r.state, "county": r.county} for r in vplan.regions],
        state_filter=plan.state_filter,
        start_month=f"{vplan.start:%Y-%m}",
        end_month=f"{vplan.end:%Y-%m}",
        operation=plan.operation,
    )
    return state.model_dump()  # same shape clients must send back (validated by the API)
