"""Answers checked against the form they answered, with value-free errors."""

import json
from pathlib import Path

import pytest

from services.api_gateway.feedback.answers import (
    FeedbackFormChanged,
    ValidatedAnswers,
    rules_from_studio,
    validate_answers,
)
from services.api_gateway.feedback.bundled_form import bundled_rules
from services.api_gateway.studio_v2 import FeedbackForm

SENTINEL = "PURPLE-RHINOCEROS-9317-SENTINEL"
VALID = {
    "translationQuality": 4,
    "performance": 5,
    "usability": 3,
    "recommendation": 9,
    "improvementIdeas": "More languages please.",
}


def _changed(answers: object) -> FeedbackFormChanged:
    with pytest.raises(FeedbackFormChanged) as caught:
        validate_answers(answers, bundled_rules())
    return caught.value


def test_a_complete_answer_set_is_split_into_numbers_and_text() -> None:
    assert validate_answers(VALID, bundled_rules()) == ValidatedAnswers(
        numeric={"translationQuality": 4, "performance": 5, "usability": 3, "recommendation": 9},
        text={"improvementIdeas": "More languages please."},
    )


@pytest.mark.parametrize("empty", [None, "", "   \n\t"])
def test_an_empty_optional_text_is_no_answer(empty: object) -> None:
    assert validate_answers({**VALID, "improvementIdeas": empty}, bundled_rules()).text == {}


def test_an_absent_optional_question_is_no_answer() -> None:
    answers = {key: value for key, value in VALID.items() if key != "improvementIdeas"}

    assert validate_answers(answers, bundled_rules()).text == {}


@pytest.mark.parametrize("answers", [[1, 2], SENTINEL, None, 4])
def test_answers_that_are_not_an_object_do_not_fit(answers: object) -> None:
    assert _changed(answers).reason == "not_an_object"


def test_an_unknown_question_does_not_fit() -> None:
    assert _changed({**VALID, SENTINEL: 3}).reason == "unknown_question"


@pytest.mark.parametrize("missing", [None, "", "  "])
def test_a_missing_required_answer_does_not_fit(missing: object) -> None:
    assert _changed({**VALID, "usability": missing}).reason == "missing_answer"


def test_an_absent_required_answer_does_not_fit() -> None:
    answers = {key: value for key, value in VALID.items() if key != "recommendation"}

    assert _changed(answers).reason == "missing_answer"


@pytest.mark.parametrize(
    "question, value",
    [
        ("translationQuality", "4"),
        ("translationQuality", True),
        ("translationQuality", 4.0),
        ("recommendation", 9.5),
        ("recommendation", [9]),
        ("improvementIdeas", 42),
        ("improvementIdeas", {"text": SENTINEL}),
    ],
)
def test_an_answer_of_the_wrong_type_does_not_fit(question: str, value: object) -> None:
    assert _changed({**VALID, question: value}).reason == "wrong_type"


@pytest.mark.parametrize(
    "question, value",
    [("usability", 0), ("usability", 6), ("recommendation", -1), ("recommendation", 11)],
)
def test_a_number_out_of_range_does_not_fit(question: str, value: int) -> None:
    assert _changed({**VALID, question: value}).reason == "out_of_range"


@pytest.mark.parametrize("question, value", [("usability", 1), ("recommendation", 0)])
def test_the_range_bounds_fit(question: str, value: int) -> None:
    assert validate_answers({**VALID, question: value}, bundled_rules()).numeric[question] == value


def test_text_over_the_limit_does_not_fit() -> None:
    assert _changed({**VALID, "improvementIdeas": "x" * 4001}).reason == "too_long"


def test_text_at_the_limit_fits() -> None:
    text = "x" * 4000

    assert validate_answers({**VALID, "improvementIdeas": text}, bundled_rules()).text == {
        "improvementIdeas": text
    }


@pytest.mark.parametrize(
    "answers",
    [
        {**VALID, SENTINEL: SENTINEL},
        {**VALID, "improvementIdeas": SENTINEL * 200},
        {**VALID, "usability": SENTINEL},
        SENTINEL,
    ],
)
def test_no_error_carries_an_answer_or_a_key(answers: object) -> None:
    error = _changed(answers)

    assert SENTINEL not in str(error)
    assert SENTINEL not in repr(error.args)
    assert error.__cause__ is None
    assert error.__context__ is None


def _studio_form() -> FeedbackForm:
    return FeedbackForm.model_validate(
        {
            "headline": "Feedback",
            "noticeHtml": "<p>Notice</p>",
            "button": "Send",
            "questions": [
                {
                    "id": "clarity",
                    "type": "rating",
                    "headline": "Clarity",
                    "question": "How clear was it?",
                    "required": True,
                    "min": 1,
                    "max": 7,
                },
                {
                    "id": "likely",
                    "type": "scale",
                    "question": "Would you use it again?",
                    "required": False,
                    "min": 0,
                    "max": 4,
                    "minLabel": "No",
                    "maxLabel": "Yes",
                },
                {
                    "id": "notes",
                    "type": "longText",
                    "question": "Anything else?",
                    "required": False,
                    "placeholder": "Type here",
                    "maxLength": 600,
                },
            ],
        }
    )


def test_studio_rules_follow_the_studio_form() -> None:
    rules = rules_from_studio(_studio_form())

    assert validate_answers({"clarity": 7, "likely": 0, "notes": "ok"}, rules) == ValidatedAnswers(
        numeric={"clarity": 7, "likely": 0}, text={"notes": "ok"}
    )
    with pytest.raises(FeedbackFormChanged):
        validate_answers({"clarity": 8}, rules)
    with pytest.raises(FeedbackFormChanged):
        validate_answers({"clarity": 3, "notes": "x" * 601}, rules)
    with pytest.raises(FeedbackFormChanged):
        validate_answers({"clarity": 3, "translationQuality": 4}, rules)


def test_the_studio_snapshot_keeps_the_questions_as_rendered() -> None:
    snapshot = rules_from_studio(_studio_form()).snapshot

    assert snapshot[0] == {
        "id": "clarity",
        "type": "rating",
        "headline": "Clarity",
        "question": "How clear was it?",
        "required": True,
        "min": 1,
        "max": 7,
    }
    assert snapshot[1]["minLabel"] == "No"
    assert snapshot[2]["maxLength"] == 600
    json.dumps(snapshot)


def test_the_bundled_fixture_is_valid_json_for_the_frontend() -> None:
    fixture = Path(__file__).parent / "fixtures" / "feedback" / "bundled_form.json"

    assert json.loads(fixture.read_text(encoding="utf-8"))
