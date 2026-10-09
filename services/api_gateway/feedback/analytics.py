"""Emitting one stored submission's analytics: a header and one event per numeric answer.

The submit path and the reconciler both call `emit_submission`, so a
re-emission sends exactly the events the first attempt did, under the same
ids: the header reuses the row's `analytics_event_id` and every answer event
derives its id from it. Free text is out of reach: a row here carries the
numeric answers and the form snapshot, never the ciphertext.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from ..quality_telemetry import FeedbackAnswer, FeedbackHeader
from ..quality_telemetry_schema import ProbeOutcome, ProbeResult
from ..session_pseudonym import SessionPseudonymizer, tenant_ref
from .bundled_form import legacy_ratings

_NUMERIC_TYPES = frozenset({"rating", "scale"})


class FeedbackTelemetry(Protocol):
    def emit_feedback(
        self, header: FeedbackHeader, answers: Sequence[FeedbackAnswer]
    ) -> ProbeResult: ...


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
    @property
    def created_at(self) -> datetime: ...


def numeric_answers(
    numeric: Mapping[str, int], snapshot: Sequence[Mapping[str, Any]]
) -> tuple[FeedbackAnswer, ...]:
    """The answered numeric questions, in form order, with the range they were asked on."""
    return tuple(
        FeedbackAnswer(
            question_id=question["id"],
            question_type=question["type"],
            value=numeric[question["id"]],
            minimum=question["min"],
            maximum=question["max"],
        )
        for question in snapshot
        if question.get("type") in _NUMERIC_TYPES and question.get("id") in numeric
    )


def emit_submission(
    telemetry: FeedbackTelemetry, pseudonymizer: SessionPseudonymizer, row: AnalyticsRow
) -> ProbeOutcome:
    """Send a stored row's events. The caller decides the row's state from the outcome.

    EMITTED: every event went out. DISABLED: nothing was attempted.
    DROPPED_DISALLOWED: the schema rejected an event, so nothing was sent and
    no retry could change that; the row is final. EXPORT_FAILED: some events
    may have gone out; the row stays pending and the reconciler re-sends all of
    them under the same ids and the same submission time, which silver and
    every gold count absorb (gold's averages count a re-sent event twice, the
    caveat they already carry).
    """
    answers = numeric_answers(row.numeric_answers, row.form_snapshot)
    ratings = legacy_ratings(row.numeric_answers, row.form_snapshot)
    header = FeedbackHeader(
        event_id=row.analytics_event_id,
        occurred_at=row.created_at,
        session_ref=row.session_ref,
        feedback_ref=pseudonymizer.feedback_reference(row.feedback_id),
        tenant_ref=tenant_ref(row.tenant_id),
        audience=row.audience,
        form_source=row.form_source,
        locale=row.form_locale,
        form_version=row.form_version,
        translation_quality=ratings.translation_quality if ratings else None,
        performance=ratings.performance if ratings else None,
        usability=ratings.usability if ratings else None,
        net_promoter_score=ratings.net_promoter_score if ratings else None,
    )
    return telemetry.emit_feedback(header, answers).outcome
