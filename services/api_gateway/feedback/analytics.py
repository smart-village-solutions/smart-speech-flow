"""Emitting one stored submission's analytics: a header and one event per numeric answer.

The submit path and the reconciler both call `emit_submission`, so a
re-emission sends exactly the events the first attempt did, under the same
ids: the header reuses the row's `analytics_event_id` and every answer event
derives its id from it. Free text is out of reach: a row here carries the
numeric answers and the form snapshot, never the ciphertext.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from ..quality_telemetry_schema import ProbeOutcome
from ..session_pseudonym import SessionPseudonymizer, tenant_ref
from .bundled_form import legacy_ratings

_NUMERIC_TYPES = frozenset({"rating", "scale"})


class AnalyticsRow(Protocol):
    """What both `FeedbackRecord` and `PendingAnalytics` carry."""

    @property
    def feedback_id(self) -> UUID: ...
    @property
    def tenant_id(self) -> str: ...
    @property
    def session_ref(self) -> str: ...
    @property
    def analytics_event_id(self) -> UUID: ...
    @property
    def audience(self) -> str: ...
    @property
    def form_source(self) -> str: ...
    @property
    def form_locale(self) -> str | None: ...
    @property
    def numeric_answers(self) -> Mapping[str, int]: ...
    @property
    def form_snapshot(self) -> Sequence[Mapping[str, Any]]: ...
    @property
    def form_version(self) -> str: ...


@dataclass(frozen=True, slots=True)
class NumericAnswer:
    question_id: str
    question_type: str
    value: int
    minimum: int
    maximum: int


def numeric_answers(
    numeric: Mapping[str, int], snapshot: Sequence[Mapping[str, Any]]
) -> tuple[NumericAnswer, ...]:
    """The answered numeric questions, in form order, with the range they were asked on."""
    return tuple(
        NumericAnswer(
            question["id"],
            question["type"],
            numeric[question["id"]],
            question["min"],
            question["max"],
        )
        for question in snapshot
        if question.get("type") in _NUMERIC_TYPES and question.get("id") in numeric
    )


def emit_submission(
    telemetry: Any, pseudonymizer: SessionPseudonymizer, row: AnalyticsRow
) -> ProbeOutcome:
    """EMITTED when every event went out; DISABLED when the header was not attempted.

    EXPORT_FAILED leaves the row pending and the reconciler re-sends all of its
    events. The ids repeat, so silver and every gold count absorb the ones that
    had arrived; gold's averages count those twice, the caveat they already
    carry. DROPPED_DISALLOWED (the schema rejected an event) also leaves the
    row pending, so the reconciler counts it as failed and
    FeedbackReconciliationFailing fires; a transient failure outranks it, since
    only that one may clear by itself.
    """
    answers = numeric_answers(row.numeric_answers, row.form_snapshot)
    ratings = legacy_ratings(row.numeric_answers, row.form_snapshot)
    feedback_ref = pseudonymizer.feedback_reference(row.feedback_id)
    tenant = tenant_ref(row.tenant_id)

    header = telemetry.emit_feedback_submitted(
        event_id=row.analytics_event_id,
        session_ref=row.session_ref,
        tenant_ref=tenant,
        feedback_ref=feedback_ref,
        audience=row.audience,
        form_source=row.form_source,
        locale=row.form_locale,
        answer_count=len(answers),
        form_version=row.form_version,
        translation_quality=ratings.translation_quality if ratings else None,
        performance=ratings.performance if ratings else None,
        usability=ratings.usability if ratings else None,
        net_promoter_score=ratings.net_promoter_score if ratings else None,
    )
    if header.outcome is ProbeOutcome.DISABLED:
        return ProbeOutcome.DISABLED

    outcomes = [header.outcome]
    for answer in answers:
        result = telemetry.emit_feedback_answer(
            submission_event_id=row.analytics_event_id,
            feedback_ref=feedback_ref,
            tenant_ref=tenant,
            audience=row.audience,
            question_id=answer.question_id,
            question_type=answer.question_type,
            value=answer.value,
            minimum=answer.minimum,
            maximum=answer.maximum,
        )
        outcomes.append(result.outcome)
    for settled in (ProbeOutcome.EXPORT_FAILED, ProbeOutcome.DROPPED_DISALLOWED):
        if settled in outcomes:
            return settled
    return ProbeOutcome.EMITTED
