"""The bundled feedback form, and which answers still feed the v1 analytics event.

The fixture is shared with the frontend's bundledFeedbackForm test, so the
form the browser renders and the rules the gateway validates cannot drift.
"""

import json
from pathlib import Path

import pytest

from services.api_gateway.feedback import bundled_form
from services.api_gateway.feedback.bundled_form import LegacyRatings, bundled_rules, legacy_ratings

FIXTURE = Path(__file__).parent / "fixtures" / "feedback" / "bundled_form.json"
BUNDLED_SNAPSHOT = json.loads(FIXTURE.read_text(encoding="utf-8"))
NUMBERS = {"translationQuality": 4, "performance": 5, "usability": 3, "recommendation": 9}


def test_the_bundled_rules_match_the_shared_fixture() -> None:
    assert list(bundled_rules().snapshot) == BUNDLED_SNAPSHOT


def test_the_bundled_ids_are_studios() -> None:
    assert [rule.id for rule in bundled_rules().questions] == [
        bundled_form.TRANSLATION_QUALITY,
        bundled_form.PERFORMANCE,
        bundled_form.USABILITY,
        bundled_form.RECOMMENDATION,
        bundled_form.IMPROVEMENT_IDEAS,
    ]


def test_the_bundled_form_yields_the_four_legacy_ratings() -> None:
    assert legacy_ratings(NUMBERS, BUNDLED_SNAPSHOT) == LegacyRatings(
        translation_quality=4, performance=5, usability=3, net_promoter_score=9
    )


def test_a_missing_answer_yields_no_legacy_ratings() -> None:
    numbers = {key: value for key, value in NUMBERS.items() if key != "usability"}

    assert legacy_ratings(numbers, BUNDLED_SNAPSHOT) is None


def _with(question_id: str, **changes: object) -> list[dict]:
    return [
        {**question, **changes} if question["id"] == question_id else question
        for question in BUNDLED_SNAPSHOT
    ]


@pytest.mark.parametrize(
    "snapshot",
    [
        _with("translationQuality", max=7),
        _with("performance", min=2),
        _with("recommendation", type="rating", min=1, max=10),
        _with("recommendation", max=5),
        [question for question in BUNDLED_SNAPSHOT if question["id"] != "performance"],
        [],
    ],
    ids=["seven-stars", "rating-from-two", "nps-as-rating", "short-scale", "no-id", "empty"],
)
def test_a_form_that_asks_differently_yields_no_legacy_ratings(snapshot: list[dict]) -> None:
    """The v1 event validates 1-5 and 0-10; anything else would be rejected forever."""
    assert legacy_ratings(NUMBERS, snapshot) is None


def test_a_fixture_change_runs_the_frontend_half_of_the_parity_check() -> None:
    """The frontend job skips pull requests that leave services/frontend/ alone."""
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "code-quality.yml"
    ).read_text(encoding="utf-8")
    frontend_job = workflow[workflow.index("  frontend-checks:") :]

    assert "tests/fixtures/feedback/" in frontend_job[: frontend_job.index("Install frontend")]
