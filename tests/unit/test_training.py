"""Step 3 training-data generation on the fixture dataset (see tests/conftest.py)."""

import json
import random
from pathlib import Path

import pytest

from agent.prompts import RETRY_INSTRUCTION
from evaluation.cases import EvalCase
from tools.schemas import ToolCall, canonical_json
from training.build import Generator, jaccard, trigrams, write_outputs
from training.grammar import Grammar, tidy
from training.pools import Pools
from training.templates import TEMPLATES, Ctx, Example, period, pick

HOLDOUT = {
    "cities": [{"city": "Denver", "state": "CO"}],
    "plans": [],
    "questions": ["Show Boulder, CO's ZORI since 2024."],
}


# ---- grammar ----------------------------------------------------------------------------------


def test_grammar_expands_nested_parts_and_slots():
    g = Grammar(
        {
            "q": ["{verb} {metric} for {place}"],
            "verb": ["Show", "{polite} show"],
            "polite": ["Please"],
        }
    )
    out = {
        g.sentence("{q}?", random.Random(i), {"metric": "rents", "place": "Mead, CO"})
        for i in range(20)
    }
    assert out == {"Show rents for Mead, CO?", "Please show rents for Mead, CO?"}


def test_grammar_rejects_unknown_parts_and_tidies():
    with pytest.raises(KeyError, match="unknown grammar part"):
        Grammar({}).expand("{nope}", random.Random(0), {})
    assert tidy("  how did  rents   change ?") == "How did rents change?"


def test_dev_split_uses_the_last_shape_only():
    shapes = ["a", "b", ("c", {"x": 1})]
    assert pick(shapes, "dev", random.Random(0)) == ("c", {"x": 1})
    assert {pick(shapes, "train", random.Random(i))[0] for i in range(30)} == {"a", "b"}


# ---- pools and periods ------------------------------------------------------------------------


@pytest.fixture
def ctx(db, validator):
    return Ctx.for_data(Pools(db, {"Denver"}, min_state_cities=2), validator)


def test_pools_exclude_holdout_names_and_keep_bare_names_unique(ctx):
    names = {c.name for m in ("zhvi", "zori") for c in ctx.pools.in_state[m]}
    assert "Denver" not in names and "Boulder" in names
    assert "Springfield" not in {c.name for c in ctx.pools.bare["zhvi"]}  # in IL and MO
    assert ("Oakwood", "OH") in ctx.pools.ambiguous_in_state


def test_year_bounds_come_from_data_coverage(ctx):
    assert (ctx.first_year["zhvi"], ctx.last_year) == (2023, 2025)  # fixture: 2023-01..2025-12


@pytest.mark.parametrize("seed", range(30))
def test_period_phrases_match_their_plan_months(ctx, seed):
    p = period(random.Random(seed), ctx, "zhvi")
    for month in (p.start, p.end):
        if month:
            assert month[:4] in p.phrase and 2023 <= int(month[:4]) <= 2025
    if p.start and p.end:
        assert p.start <= p.end


# ---- end-to-end generation ----------------------------------------------------------------------


@pytest.fixture
def built(db):
    gen = Generator(db, HOLDOUT, [], min_state_cities=2)
    return gen, gen.generate(120, seed=1)


def test_generation_covers_scenarios_with_valid_canonical_targets(built):
    _, items = built
    assert {b.example.scenario for b in items} >= {
        "standard",
        "scope",
        "refusal",
        "follow_up",
        "retry",
    }
    for b in items:
        last = b.record["messages"][-1]
        assert last["role"] == "assistant"
        assert canonical_json(ToolCall.model_validate_json(last["content"])) == last["content"]
        assert b.record["messages"][0]["role"] == "system"


def test_holdout_cities_never_appear(built):
    _, items = built
    for b in items:
        plan = b.example.target["call"].get("plan") or {}
        assert all(c["city"] != "Denver" for c in plan.get("cities", []))


def test_retry_examples_carry_the_agents_feedback(built):
    _, items = built
    retries = [b for b in items if b.example.scenario == "retry"]
    assert retries
    for b in retries:
        bad, feedback = b.record["messages"][-3], b.record["messages"][-2]
        assert bad["role"] == "assistant" and RETRY_INSTRUCTION in feedback["content"]


def test_generation_is_deterministic(db):
    a = Generator(db, HOLDOUT, [], min_state_cities=2).generate(40, seed=7)
    b = Generator(db, HOLDOUT, [], min_state_cities=2).generate(40, seed=7)
    assert [x.record for x in a] == [y.record for y in b]


def test_near_duplicates_of_eval_questions_are_rejected(db):
    case = EvalCase.model_validate(
        {
            "id": "e1",
            "family": "single_city",
            "question": "How did rents in Boulder, CO change?",
            "gold_call": {
                "tool": "analyze",
                "plan": {
                    "metric": "zori",
                    "cities": [{"city": "Boulder", "state": "CO"}],
                    "operation": "change",
                },
            },
            "expected_response": "answer",
        }
    )
    assert jaccard(trigrams("how did rents in boulder co change"), trigrams(case.question)) >= 0.6
    gen = Generator(db, HOLDOUT, [case], min_state_cities=2)
    plan = {"metric": "zori", "cities": [{"city": "Boulder", "state": "CO"}], "operation": "change"}
    close = Example(
        "t",
        "standard",
        "how did rents in boulder, co change",
        {"call": {"tool": "analyze", "plan": plan}},
        "answer",
    )
    far = Example(
        "t",
        "standard",
        "Plot Boulder, CO rental prices month by month",
        {"call": {"tool": "analyze", "plan": {**plan, "operation": "series"}}},
        "answer",
    )
    assert gen.check(close)[0] == "near_duplicate_of_eval"
    assert gen.check(far)[0] is None


def test_outputs_and_report_are_written(built, tmp_path):
    gen, items = built
    meta = {
        "data_version": "test",
        "seed": 1,
        "requested": 120,
        "dataset_version": "x",
        "prompt_version": "planner-v2",
        "holdout_file": "h",
        "rejected_counter": gen.rejected,
    }
    s = write_outputs(items, meta, tmp_path / "data", tmp_path / "report")
    lines = (tmp_path / "data" / "train.jsonl").read_text().splitlines()
    assert lines and json.loads(lines[0])["split"] == "train"
    assert s["examples"] == len(items)
    assert "Rejected candidates" in (tmp_path / "report" / "report.md").read_text()
    assert "## standard" in (tmp_path / "report" / "samples.md").read_text()


def test_every_template_is_registered_once():
    ids = [t.id for t in TEMPLATES]
    assert len(ids) == len(set(ids)) and len(ids) >= 35


# ---- review follow-ups --------------------------------------------------------------------------


def test_follow_up_context_matches_what_the_api_sends(built, db):
    from agent.prompts import planner_messages
    from tools.schemas import ConversationState

    _, items = built
    follow = [b for b in items if b.example.scenario == "follow_up" and b.example.state]
    assert follow
    for b in follow:
        ex = b.example
        via_api = ConversationState.model_validate(ex.state).model_dump(exclude_defaults=True)
        assert ex.state == via_api
        assert "null" not in b.record["messages"][0]["content"].split("Previous-turn context:")[1]
        expected = planner_messages(db, ex.question, ex.history, via_api)
        assert b.record["messages"][: len(expected)] == expected


def test_aggregate_wording_never_uses_rank_words():
    from training.templates import AGG_WORDS

    words = {w for ws in AGG_WORDS.values() for w in ws}
    assert not words & {"highest", "lowest", "top", "bottom"}


def test_data_version_tracks_prompt_and_schema_sources():
    from training.build import VERSIONED_SOURCES

    names = {p.name for p in VERSIONED_SOURCES}
    assert {"prompts.py", "schemas.py", "templates.py", "build.py"} <= names
    assert all(p.exists() for p in VERSIONED_SOURCES)


class _FakeDB:
    """Just what Pools reads: regions (in a given order) and size ranks that all tie."""

    def __init__(self, regions):
        self.regions = regions

    def query(self, sql, params):
        return [{"region_id": rid, "sr": 7} for rid in self.regions]


def test_pools_do_not_depend_on_database_row_order():
    """Regression: DuckDB's GROUP BY order differs between runs, and most real regions share a
    size rank, so builds on different machines (or processes) produced different data."""
    from housing.db import Region

    regions = {
        str(i): Region(str(i), f"Town{i}", "CO", "X County", frozenset({"zhvi"})) for i in range(12)
    }
    forward = Pools(_FakeDB(regions), set(), min_state_cities=2)
    backward = Pools(_FakeDB(dict(reversed(list(regions.items())))), set(), min_state_cities=2)
    assert [c.region_id for c in forward.in_state["zhvi"]] == [
        c.region_id for c in backward.in_state["zhvi"]
    ]
    rng_a, rng_b = random.Random(5), random.Random(5)
    assert [forward.city(rng_a, "zhvi").name for _ in range(10)] == [
        backward.city(rng_b, "zhvi").name for _ in range(10)
    ]


# ---- data v2 (Step 3c) ------------------------------------------------------------------------


def test_methodology_examples_call_search_knowledge(ctx):
    from training.templates import methodology

    rng = random.Random(4)
    examples = [methodology(rng, ctx, "train") for _ in range(30)]
    assert all(e.target["call"]["tool"] == "search_knowledge" for e in examples)
    assert all(e.expect == "search" and e.scenario == "methodology" for e in examples)
    assert len({e.target["call"]["query"] for e in examples}) >= 5  # several topics


def _draws(builder, ctx, n, seed):
    """Call a builder n times, skipping draws that hit an empty fixture pool (the generator does
    the same: the small fixture has no state with two ZORI cities)."""
    rng, out = random.Random(seed), []
    for _ in range(n):
        try:
            ex = builder(rng, ctx, "train")
        except IndexError:
            continue
        if ex is not None:
            out.append(ex)
    return out


def test_refusal_texts_vary_within_a_kind(ctx):
    from training.templates import refusal_builder

    texts = {e.target["call"]["text"] for e in _draws(refusal_builder("r", "forecast"), ctx, 80, 9)}
    assert len(texts) >= 3
    assert not any(ch.isdigit() for t in texts for ch in t)  # refusals never state numbers


def test_follow_up_history_often_omits_the_state_and_context_the_county(built):
    _, items = built
    follows = [
        b.example
        for b in items
        if b.example.scenario == "follow_up" and b.example.state and b.example.state.get("cities")
    ]
    assert follows
    city = lambda e: e.state["cities"][0]  # noqa: E731
    bare_history = [e for e in follows if f"{city(e)['city']}," not in e.history[0]["content"]]
    no_county = [e for e in follows if "county" not in city(e)]
    assert bare_history and no_county
    for e in follows:  # the gold call still takes each context city's state from the context
        context = {c["city"]: c["state"] for c in e.state["cities"]}
        for c in e.target["call"].get("plan", {}).get("cities", []):
            if c["city"] in context:
                assert c.get("state") == context[c["city"]]


def test_rank_follow_up_can_switch_to_an_aggregate(ctx):
    from training.templates import follow_builder

    plans = [e.target["call"]["plan"] for e in _draws(follow_builder("rank"), ctx, 300, 0)]
    assert {"rank", "aggregate"} <= {p["operation"] for p in plans}
    for p in plans:
        if p["operation"] == "aggregate":
            assert "rank_by" not in p and p["aggregate"]


@pytest.mark.parametrize("kind", ["year", "range", "since", "month_since", "month_range"])
def test_only_the_none_kind_gives_an_empty_period(ctx, kind):
    for seed in range(200):  # includes starts in the last full year
        p = period(random.Random(seed), ctx, "zhvi", (kind,))
        assert p.phrase and p.start
        if p.end:
            assert p.start < p.end or kind in ("year",)


def test_methodology_lead_in_keeps_sentence_case(ctx):
    from training.templates import methodology

    rng = random.Random(1)
    for _ in range(200):
        q = methodology(rng, ctx, "train").question
        assert ", When " not in q and ", How " not in q and ", Why " not in q


def test_no_generator_shape_copies_an_eval_question():
    """Fixed shapes are written independently of the eval set; a verbatim copy would be filtered
    out anyway, but it would mean tuning the data on the test questions."""
    import training.templates as T
    from evaluation.cases import load_cases
    from evaluation.holdout import normalize_question

    eval_questions = {
        normalize_question(c.question)
        for c in load_cases(Path(__file__).resolve().parents[2] / "evaluation/cases/v1.jsonl")
    }
    shapes = []
    for value in vars(T).values():
        if isinstance(value, list):
            for item in value:
                text = item[0] if isinstance(item, tuple) else item
                if isinstance(text, str):
                    shapes.append(text)
    shapes += [s for _, topic_shapes in T.METHODOLOGY_TOPICS for s in topic_shapes]
    literal = [s for s in shapes if "{" not in s]
    assert literal and not [s for s in literal if normalize_question(s) in eval_questions]
