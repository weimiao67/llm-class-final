from datetime import date

import pytest

from agent.grounding import clarification_text, numbers_in_text, unsupported_numbers
from tools.schemas import ToolError

EVIDENCE = {
    "period": {"start_month": date(2025, 1, 1), "end_month": date(2025, 12, 1)},
    "summary": {"cities": [{"start_value": 524000.0, "end_value": 535000.0, "pct_change": 2.1}]},
}


def test_numbers_in_text_handles_commas_decimals_and_signs():
    assert numbers_in_text("$535,000 rose -2.10% in 3 months") == [
        (535000.0, 0),
        (-2.1, 2),
        (3.0, 0),
    ]


@pytest.mark.parametrize(
    "answer",
    [
        "Denver rose from $524,000 to $535,000 (2.1%) in 2025.",
        "It went up about 2% between Jan 2025 and Dec 2025.",  # fewer decimals is fine
        "ZHVI fell -2.1%.",  # sign-insensitive
    ],
)
def test_grounded_answers_pass(answer):
    assert unsupported_numbers(answer, EVIDENCE) == []


@pytest.mark.parametrize(
    "answer, bad",
    [
        ("Denver rose to $540,000.", ["540000"]),
        ("Growth was 2.4%.", ["2.4"]),
        ("Prices will reach $600,000 by 2027.", ["600000", "2027"]),
    ],
)
def test_invented_numbers_are_flagged(answer, bad):
    assert unsupported_numbers(answer, EVIDENCE) == bad


def test_numbers_from_question_are_allowed():
    assert unsupported_numbers("Here are the top 5 cities.", {}, "Show the top 5") == []


def test_clarification_lists_candidates():
    err = ToolError(
        kind="ambiguous_city",
        message="",
        details={
            "cities": [
                {
                    "query": {"city": "Oakwood"},
                    "candidates": [
                        {"city": "Oakwood", "state": "OH", "county": "Montgomery County"},
                        {"city": "Oakwood", "state": "OH", "county": "Cuyahoga County"},
                    ],
                }
            ]
        },
    )
    text = clarification_text(err)
    assert "Montgomery County" in text and "Cuyahoga County" in text and text.endswith("?")


def test_not_found_text_offers_suggestions():
    err = ToolError(
        kind="city_not_found",
        message="",
        details={"cities": [{"query": {"city": "Denvr"}, "suggestions": ["Denver, CO"]}]},
    )
    assert "Did you mean Denver, CO?" in clarification_text(err)


def test_iso_months_in_prose_count_as_years():
    assert unsupported_numbers("In 2025-12 the value was $535,000.", EVIDENCE) == []
    assert unsupported_numbers("On 2025-12-01 it was $535,000.", EVIDENCE) == []


def test_cross_state_ambiguity_asks_for_the_state():
    candidates = [
        {"city": "Springfield", "state": st, "county": f"{st} County"}
        for st in ["IL", "MO", "MA", "OH", "OR", "VA", "TN", "KY", "MI", "NJ", "PA", "VT", "GA"]
    ]
    err = ToolError(
        kind="ambiguous_city",
        message="",
        details={"cities": [{"query": {"city": "Springfield"}, "candidates": candidates}]},
    )
    text = clarification_text(err)
    assert text.startswith('"Springfield" exists in 13 states (GA, IL,')
    assert "and 1 more" in text and text.endswith("Which state do you mean?")
    assert "County" not in text


def test_numbers_in_warning_sentences_are_evidence():
    evidence = {
        "summary": {"cities": [{"region_id": "11093", "end_value": 535000.0}]},
        "warnings": ["Summary shows the 10 largest of 1,003 cities (by Zillow size rank)."],
    }
    answer = "Of 1,003 cities, the 10 largest are shown; Denver ends at $535,000."
    assert unsupported_numbers(answer, evidence) == []
    # identifiers without spaces are not evidence
    assert unsupported_numbers("Its value is 11093.", evidence) == ["11093"]
