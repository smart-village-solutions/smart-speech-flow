"""Accepting one feedback submission.

The ordering is the contract: the transactional write commits before any
telemetry is attempted, so a Collector outage can never turn a stored
submission into an API failure, and a storage failure can never leave an
analytics event describing a row that does not exist.
"""

from __future__ import annotations

import calendar
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID, uuid4

from ..quality_telemetry import ProbeOutcome
from ..session_pseudonym import MISSING_REFERENCE, feedback_ref, session_ref
from .models import (
    MAX_IMPROVEMENTS_LENGTH,
    RETENTION_POLICY_VERSION,
    AnalyticsState,
    FeedbackRecord,
    FeedbackSubmissionRequest,
    FeedbackTextTooLong,
)

_RETENTION_MONTHS = 12


class UnknownSession(LookupError):
    """A session id was supplied but the session manager does not know it."""


class FeedbackService:
    def __init__(
        self,
        *,
        repository: Any,
        cipher: Any,
        tenant_resolver: Any,
        session_manager: Any,
        telemetry: Any,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._repository = repository
        self._cipher = cipher
        self._tenant_resolver = tenant_resolver
        self._session_manager = session_manager
        self._telemetry = telemetry
        self._clock = clock

    async def submit(self, request: FeedbackSubmissionRequest) -> UUID:
        text = self._validated_text(request.improvements)
        reference = self._resolve_session(request.session_id)
        tenant_id = await self._tenant_resolver.resolve(request.session_id)

        feedback_id = uuid4()
        analytics_event_id = uuid4()
        created_at = self._clock()

        ciphertext = None
        if text is not None:
            ciphertext = self._cipher.encrypt(text, feedback_id=feedback_id, tenant_id=tenant_id)

        record = FeedbackRecord(
            feedback_id=feedback_id,
            tenant_id=tenant_id,
            session_ref=reference,
            translation_quality=request.translation_quality,
            performance=request.performance,
            usability=request.usability,
            net_promoter_score=request.net_promoter_score,
            improvements_ciphertext=ciphertext,
            form_version=request.form_version,
            retention_policy_version=RETENTION_POLICY_VERSION,
            consent_snapshot={
                "form_version": request.form_version,
                "retention_policy_version": RETENTION_POLICY_VERSION,
                "agreed_at": created_at.isoformat(),
                "manifestation": "form_submission",
            },
            analytics_event_id=analytics_event_id,
            analytics_state=AnalyticsState.PENDING,
            created_at=created_at,
            expires_at=_add_months(created_at, _RETENTION_MONTHS),
        )

        # Commit first. Everything after this point is best-effort.
        await self._repository.store(record)

        result = self._telemetry.emit_feedback_submitted(
            event_id=analytics_event_id,
            session_ref=reference,
            feedback_ref=feedback_ref(feedback_id),
            translation_quality=request.translation_quality,
            performance=request.performance,
            usability=request.usability,
            net_promoter_score=request.net_promoter_score,
            form_version=request.form_version,
        )

        if result.outcome is ProbeOutcome.EMITTED:
            await self._repository.mark_analytics_delivered(feedback_id, tenant_id)
        elif result.outcome is ProbeOutcome.DISABLED:
            # Nothing will ever drain a backlog for an event type this
            # deployment does not emit, so it is not a backlog.
            await self._repository.mark_analytics_state(
                feedback_id, AnalyticsState.NOT_APPLICABLE, tenant_id
            )

        return feedback_id

    @staticmethod
    def _validated_text(improvements: str | None) -> str | None:
        """Enforce the length here rather than in the Pydantic model.

        Pydantic attaches the offending value to every error it raises and
        FastAPI copies that into the 422 body, so a constraint on the model
        would publish the free text. FeedbackTextTooLong carries no copy of it.
        """
        if improvements is None:
            return None
        if len(improvements) > MAX_IMPROVEMENTS_LENGTH:
            raise FeedbackTextTooLong(
                f"improvements must be at most {MAX_IMPROVEMENTS_LENGTH} characters"
            )
        # Whitespace is not a submission: storing it would produce ciphertext
        # that decrypts to nothing an authorised reader can act on.
        return improvements if improvements.strip() else None

    def _resolve_session(self, session_id: str | None) -> str:
        if session_id is None:
            return MISSING_REFERENCE
        if self._session_manager.get_session(session_id) is None:
            raise UnknownSession
        return session_ref(session_id)


def _add_months(moment: datetime, months: int) -> datetime:
    """Calendar arithmetic without a dateutil dependency.

    Only whole years are needed today, but the general form keeps a future
    retention policy from silently landing on the wrong day. 29 February plus
    twelve months clamps to 28 February rather than overflowing into March.
    """
    month_index = moment.month - 1 + months
    year = moment.year + month_index // 12
    month = month_index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)
