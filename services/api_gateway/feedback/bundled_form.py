"""The form SSF shows when Studio provides none, and the v1 analytics it feeds.

It mirrors the frontend's `bundledFeedbackForm`; both are tested against
tests/fixtures/feedback/bundled_form.json, and migration 004 stores the same
snapshot on every converted row.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from .answers import FormRules, QuestionRule
from .models import MAX_IMPROVEMENTS_LENGTH

# Studio's ids for the bundled questions, so a bundled answer and a Studio
# answer to the same question share one id.
TRANSLATION_QUALITY: Final = "translationQuality"
PERFORMANCE: Final = "performance"
USABILITY: Final = "usability"
RECOMMENDATION: Final = "recommendation"
IMPROVEMENT_IDEAS: Final = "improvementIdeas"

_QUESTIONS: Final = (
    QuestionRule(TRANSLATION_QUALITY, "rating", True, 1, 5),
    QuestionRule(PERFORMANCE, "rating", True, 1, 5),
    QuestionRule(USABILITY, "rating", True, 1, 5),
    QuestionRule(RECOMMENDATION, "scale", True, 0, 10),
    QuestionRule(IMPROVEMENT_IDEAS, "longText", False, max_length=MAX_IMPROVEMENTS_LENGTH),
)


def rule_snapshot(rule: QuestionRule) -> dict[str, Any]:
    """A question as stored when no Studio text was shown with it."""
    shown: dict[str, Any] = {"id": rule.id, "type": rule.type, "required": rule.required}
    if rule.type == "longText":
        shown["maxLength"] = rule.max_length
    else:
        shown["min"] = rule.min
        shown["max"] = rule.max
    return shown


def bundled_rules() -> FormRules:
    return FormRules(_QUESTIONS, tuple(rule_snapshot(rule) for rule in _QUESTIONS))


@dataclass(frozen=True, slots=True)
class LegacyRatings:
    """The four numbers the v1 `feedback_submitted` event carries."""

    translation_quality: int
    performance: int
    usability: int
    net_promoter_score: int


# The ranges the v1 event validates. A form asking these ids differently would
# be rejected by the event schema on every attempt, so it emits nothing at all.
_LEGACY_QUESTIONS: Final = {rule.id: rule for rule in _QUESTIONS if rule.type != "longText"}


def legacy_rating(
    question_id: str, numeric: Mapping[str, int], snapshot: Sequence[Mapping[str, Any]]
) -> int | None:
    """One bundled rating's answer, if the form asked it exactly as the bundled form does."""
    rule = _LEGACY_QUESTIONS[question_id]
    for question in snapshot:
        if question.get("id") == question_id:
            asked = (question.get("type"), question.get("min"), question.get("max"))
            return numeric.get(question_id) if asked == (rule.type, rule.min, rule.max) else None
    return None


def legacy_ratings(
    numeric: Mapping[str, int], snapshot: Sequence[Mapping[str, Any]]
) -> LegacyRatings | None:
    """The v1 event's numbers, when the form asked all four bundled ratings and all were answered."""
    ratings = [legacy_rating(question_id, numeric, snapshot) for question_id in _LEGACY_QUESTIONS]
    answered = [rating for rating in ratings if rating is not None]
    if len(answered) != len(_LEGACY_QUESTIONS):
        return None
    translation_quality, performance, usability, net_promoter_score = answered
    return LegacyRatings(
        translation_quality=translation_quality,
        performance=performance,
        usability=usability,
        net_promoter_score=net_promoter_score,
    )
