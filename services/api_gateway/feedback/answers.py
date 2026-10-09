"""Checking a feedback submission's answers against the form it answered.

Every error here is value-free: it names a reason, never an id or an answer,
because an unknown id is user input as much as an answer is. The route turns
FeedbackFormChanged into a 409 whose body is fixed text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ..studio_v2 import FeedbackForm, LongTextQuestion

QuestionType = Literal["rating", "scale", "longText"]
MismatchReason = Literal[
    "not_an_object",
    "unknown_question",
    "missing_answer",
    "wrong_type",
    "out_of_range",
    "too_long",
    "form_missing",
]


@dataclass(frozen=True, slots=True)
class QuestionRule:
    id: str
    type: QuestionType
    required: bool
    min: int | None = None
    max: int | None = None
    max_length: int | None = None


@dataclass(frozen=True, slots=True)
class FormRules:
    """What a form accepts, and the questions as they were shown, for storage."""

    questions: tuple[QuestionRule, ...]
    snapshot: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class ValidatedAnswers:
    numeric: dict[str, int]
    text: dict[str, str]


class FeedbackFormChanged(LookupError):
    """The answers do not fit the form; the browser should reload it."""

    def __init__(self, reason: MismatchReason) -> None:
        super().__init__(f"the answers do not fit the form ({reason})")
        self.reason: MismatchReason = reason


def validate_answers(answers: object, rules: FormRules) -> ValidatedAnswers:
    if not isinstance(answers, dict):
        raise FeedbackFormChanged("not_an_object")
    known = {rule.id for rule in rules.questions}
    if any(key not in known for key in answers):
        raise FeedbackFormChanged("unknown_question")

    numeric: dict[str, int] = {}
    text: dict[str, str] = {}
    for rule in rules.questions:
        value = _present(answers.get(rule.id))
        if value is None:
            if rule.required:
                raise FeedbackFormChanged("missing_answer")
        elif rule.type == "longText":
            text[rule.id] = _text(value, rule)
        else:
            numeric[rule.id] = _number(value, rule)
    return ValidatedAnswers(numeric, text)


def _present(value: object) -> object:
    """None for no answer. Whitespace is not an answer, so it stores nothing."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _number(value: object, rule: QuestionRule) -> int:
    # bool is an int subclass, and JSON `true` must not count as one star.
    if isinstance(value, bool) or not isinstance(value, int):
        raise FeedbackFormChanged("wrong_type")
    if rule.min is not None and value < rule.min:
        raise FeedbackFormChanged("out_of_range")
    if rule.max is not None and value > rule.max:
        raise FeedbackFormChanged("out_of_range")
    return value


def _text(value: object, rule: QuestionRule) -> str:
    if not isinstance(value, str):
        raise FeedbackFormChanged("wrong_type")
    if rule.max_length is not None and len(value) > rule.max_length:
        raise FeedbackFormChanged("too_long")
    return value


def rules_from_studio(form: FeedbackForm) -> FormRules:
    rules = tuple(
        (
            QuestionRule(
                question.id, question.type, question.required, max_length=question.max_length
            )
            if isinstance(question, LongTextQuestion)
            else QuestionRule(
                question.id, question.type, question.required, question.min, question.max
            )
        )
        for question in form.questions
    )
    snapshot = tuple(question.model_dump(mode="json", by_alias=True) for question in form.questions)
    return FormRules(rules, snapshot)
