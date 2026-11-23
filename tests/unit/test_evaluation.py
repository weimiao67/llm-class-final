"""Eval set integrity (no data needed) and scorer/runner behavior on the fixture dataset."""

import json
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.model_clients.stub import ScriptedModelClient
from evaluation.cases import EvalCase, load_cases
from evaluation.holdout import Holdout, build_holdout
from evaluation.oracle import OracleModelClient
from evaluation.runner import run_eval, write_report
from evaluation.scoring import plan_key, rows_key

ROOT = Path(__file__).resolve().parents[2]
V1 = ROOT / "evaluation" / "cases" / "v1.jsonl"


# ---- the frozen v1 set ------------------------------------------------------------------------


def test_v1_loads_with_planned_family_mix():
    cases = load_cases(V1)
    assert Counter(c.family for c in cases) == {
        "single_city": 35,
        "extrema": 20,
        "multi_city": 30,
        "aggregate": 20,
        "coverage": 10,
        "methodology": 15,
        "follow_up": 20,
        "ambiguous": 15,
        "boundary": 25,
        "injection": 10,
    }


def test_v1_holdout_file_is_in_sync():
    stored = json.loads((ROOT / "evaluation" / "cases" / "v1_holdout.json").read_text())
    rebuilt = build_holdout(load_cases(V1), "evaluation/cases/v1.jsonl")
    assert stored == rebuilt


def test_v1_holdout_covers_statewide_cases():
    stored = json.loads((ROOT / "evaluation" / "cases" / "v1_holdout.json").read_text())
    statewide = [p for p in stored["plans"] if p.get("state_filter") and not p.get("cities")]
    assert len(statewide) >= 40  # these name no city, so only the plan guard protects them


# ---- schema -----------------------------------------------------------------------------------


def case(**kw):
    base = {
        "id": "t-1",
        "family": "single_city",
        "question": "q",
        "gold_call": {
            "tool": "analyze",
            "plan": {"metric": "zhvi", "cities": [{"city": "Denver"}], "operation": "change"},
        },
        "expected_response": "answer",
    }
    return EvalCase.model_validate({**base, **kw})


def test_case_rejects_invalid_gold_plan():
    with pytest.raises(ValidationError):
        case(gold_call={"tool": "analyze", "plan": {"metric": "zhvi", "operation": "change"}})


def test_case_respond_kind_must_match_expected_response():
    with pytest.raises(ValidationError, match="must equal expected_response"):
        case(gold_call={"tool": "respond", "kind": "unsupported"}, expected_response="clarify")


def test_alt_calls_must_use_same_tool():
    with pytest.raises(ValidationError, match="same tool"):
        case(alt_calls=[{"tool": "respond", "kind": "answer"}])


def test_duplicate_ids_rejected(tmp_path):
    line = case().model_dump_json()
    path = tmp_path / "c.jsonl"
    path.write_text(line + "\n" + line + "\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_cases(path)


# ---- normalization ----------------------------------------------------------------------------


def test_plan_key_treats_default_and_explicit_period_as_equal(validator):
    a = {"metric": "zhvi", "cities": [{"city": "Denver", "state": "CO"}], "operation": "change"}
    b = {**a, "cities": [{"city": "denver"}], "start_month": "2023-01", "end_month": "2025-12"}
    assert plan_key(a, validator) == plan_key(b, validator)


def test_plan_key_distinguishes_rank_order_and_limit(validator):
    a = {"metric": "zhvi", "state_filter": "CO", "operation": "rank", "rank_by": "value"}
    assert plan_key(a, validator) != plan_key({**a, "order": "asc"}, validator)
    assert plan_key(a, validator) != plan_key({**a, "limit": 3}, validator)


def test_plan_key_for_unresolvable_plans_uses_raw_fields(validator):
    a = {"metric": "zhvi", "cities": [{"city": "Oakwood", "state": "OH"}], "operation": "series"}
    assert plan_key(a, validator)[0] == "raw"
    b = {**a, "cities": [{"city": "oakwood ", "state": "OH"}]}
    assert plan_key(a, validator) == plan_key(b, validator)


def test_rows_key_is_order_insensitive_and_handles_none():
    a = [{"x": 1.004, "y": None}, {"x": 2.0, "y": 3.0}]
    assert rows_key(a) == rows_key(list(reversed(a)))
    assert rows_key(a) == rows_key([{"y": 3.0, "x": 2.0}, {"y": None, "x": 1.0}])


# ---- runner + scorer --------------------------------------------------------------------------

FIXTURE_CASES = [
    case(
        id="ok",
        gold_call={
            "tool": "analyze",
            "plan": {
                "metric": "zhvi",
                "cities": [{"city": "Denver", "state": "CO"}],
                "start_month": "2025-01",
                "end_month": "2025-12",
                "operation": "change",
            },
        },
    ),
    case(
        id="amb",
        family="ambiguous",
        gold_call={
            "tool": "analyze",
            "plan": {
                "metric": "zhvi",
                "cities": [{"city": "Oakwood", "state": "OH"}],
                "operation": "series",
            },
        },
        expected_response="clarify",
    ),
    case(
        id="fc",
        family="boundary",
        gold_call={"tool": "respond", "kind": "out_of_scope"},
        expected_response="out_of_scope",
    ),
    case(
        id="kb",
        family="methodology",
        gold_call={"tool": "search_knowledge", "query": "what is zori", "top_k": 3},
        expected_response="answer",
    ),
]


def test_oracle_scores_perfectly_on_fixture(db):
    results = run_eval(FIXTURE_CASES, db, OracleModelClient)
    assert all(r.success for r in results), [r.failures for r in results]
    by_id = {r.id: r for r in results}
    assert by_id["ok"].exec_match and by_id["ok"].plan_match
    assert by_id["amb"].kind == "clarify" and by_id["amb"].exec_match is None
    assert by_id["kb"].kind == "error" and by_id["kb"].kind_correct  # scored on tool choice


def test_wrong_city_fails_execution_and_plan(db):
    wrong = {
        "call": {
            "tool": "analyze",
            "plan": {
                "metric": "zhvi",
                "cities": [{"city": "Boulder", "state": "CO"}],
                "start_month": "2025-01",
                "end_month": "2025-12",
                "operation": "change",
            },
        }
    }
    results = run_eval(FIXTURE_CASES[:1], db, lambda c: ScriptedModelClient([wrong, "", ""]))
    r = results[0]
    assert not r.success and not r.exec_match and not r.plan_match
    assert r.kind == "answer" and r.tool_correct


def test_invalid_first_output_is_counted(db):
    gold = {"call": FIXTURE_CASES[2].gold_call | {"text": "No forecasts."}}
    results = run_eval(FIXTURE_CASES[2:3], db, lambda c: ScriptedModelClient(["oops", gold]))
    r = results[0]
    assert not r.first_output_valid and not r.tool_correct and r.success  # recovered on retry


def test_report_files_are_written(db, tmp_path):
    results = run_eval(FIXTURE_CASES, db, OracleModelClient)
    report = write_report(
        tmp_path / "run1",
        results,
        model_id="oracle",
        db=db,
        cases_file="fixture",
        knowledge_base=False,
    )
    assert report["overall"]["turn_success"]["rate"] == 1.0
    assert {p.name for p in (tmp_path / "run1").iterdir()} == {
        "report.md",
        "summary.json",
        "results.jsonl",
    }
    assert "Execution accuracy" in (tmp_path / "run1" / "report.md").read_text()


# ---- hold-out guard ---------------------------------------------------------------------------

HOLDOUT = {
    "cities": [{"city": "Mead", "state": "CO"}],
    "plans": [
        {
            "metric": "zhvi",
            "state_filter": "CO",
            "operation": "rank",
            "rank_by": "pct_change",
            "start_month": "2025-01",
            "end_month": "2025-12",
        },
    ],
    "questions": ["Rank Colorado cities by ZHVI growth in 2025."],
}


def test_holdout_rejects_same_statewide_plan_however_phrased(validator):
    h = Holdout(HOLDOUT, validator)
    same = dict(HOLDOUT["plans"][0], limit=10, order="desc")  # defaults spelled out
    assert h.conflicts("Which CO towns grew fastest during 2025?", same) == ["plan"]
    other_year = dict(HOLDOUT["plans"][0], start_month="2024-01", end_month="2024-12")
    assert h.conflicts("Which CO towns grew fastest during 2024?", other_year) == []


def test_holdout_rejects_eval_city_in_any_state_and_eval_question(validator):
    h = Holdout(HOLDOUT, validator)
    plan = {"metric": "zhvi", "cities": [{"city": "mead", "state": "NE"}], "operation": "series"}
    assert h.conflicts("Show Mead home values", plan) == ["city"]
    assert h.conflicts("rank colorado cities by zhvi growth in 2025") == ["question"]


# ---- review follow-ups --------------------------------------------------------------------------


def test_recorder_and_oracle_follow_the_step_not_the_constraint():
    import dataclasses

    from agent import decoding
    from evaluation.runner import RecordingClient

    unconstrained_plan = dataclasses.replace(decoding.PLAN, constrained=False)
    rec = RecordingClient(OracleModelClient(FIXTURE_CASES[0]))
    out = rec.complete([{"role": "user", "content": "q"}], unconstrained_plan)
    assert '"analyze"' in out.text and rec.planner_outputs == [out.text]
    rec.complete([{"role": "user", "content": "q"}], decoding.ANSWER)
    assert len(rec.planner_outputs) == 1


def test_clarification_cases_report_how_they_were_reached(db):
    direct = {"call": {"tool": "respond", "kind": "clarify", "text": "Which Oakwood?"}}
    results = run_eval(FIXTURE_CASES[1:2], db, lambda c: ScriptedModelClient([direct]))
    r = results[0]
    assert r.success and not r.tool_correct
    from evaluation.scoring import summarize

    assert summarize(results)["overall"]["clarify_via_analyze"]["rate"] == 0.0


def test_run_ids_are_folder_safe():
    import importlib.util

    spec = importlib.util.spec_from_file_location("run_eval", ROOT / "scripts" / "run_eval.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.safe_name("meta-llama/Llama-3.2-3B-Instruct") == "meta-llama-Llama-3.2-3B-Instruct"
    assert mod.safe_name("///") == "model"


def test_results_keep_raw_planner_outputs_plan_and_trace(db, tmp_path):
    bad = '{"call": {"tool": "analyze", "plan": {"metric": "zhvi", "operation": "change"}}}'
    gold = {"call": FIXTURE_CASES[0].gold_call}
    results = run_eval(FIXTURE_CASES[:1], db, lambda c: ScriptedModelClient([bad, gold, ""]))
    r = results[0]
    assert r.planner_outputs[0] == bad and len(r.planner_outputs) == 2
    assert r.plan["cities"][0]["city"] == "Denver"
    assert [e["status"] for e in r.trace][:2] == ["retry", "ok"]
    write_report(
        tmp_path / "run", results, model_id="m", db=db, cases_file="f", knowledge_base=False
    )
    saved = json.loads((tmp_path / "run" / "results.jsonl").read_text().splitlines()[0])
    assert saved["planner_outputs"][0] == bad
