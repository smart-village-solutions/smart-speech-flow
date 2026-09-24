"""Accepting one feedback submission.

The ordering is the contract: the transactional write commits before any
telemetry is attempted, so a Collector outage can never turn a stored
submission into an API failure, and a storage failure can never leave an
analytics event describing a row that does not exist.
"""

from __future__ import annotations

import calendar
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Final, Optional, Protocol
from uuid import UUID, uuid4

from ..quality_telemetry import ProbeOutcome
from ..session_pseudonym import MISSING_REFERENCE, SessionPseudonymizer, tenant_ref
from ..tenant_session import TenantSessionKey
from .models import (
    MAX_IMPROVEMENTS_LENGTH,
    RETENTION_POLICY_VERSION,
    AnalyticsState,
    FeedbackRecord,
    FeedbackSubmissionRequest,
    FeedbackTextTooLong,
)
from .repository import FeedbackRepository
from .tenant import TenantResolver

logger = logging.getLogger(__name__)

_RETENTION_MONTHS = 12

FEEDBACK_GRACE_ENV: Final[str] = "SSF_FEEDBACK_GRACE_MINUTES"
DEFAULT_GRACE_MINUTES: Final[int] = 30


def _configured_grace_window() -> timedelta:
    """How long after a conversation ends its feedback is still accepted.

    `0` turns the window off, restoring the refusal that shipped before it
    existed -- a deployment whose privacy rules end with the conversation
    needs a way to say so.

    Anything unusable falls back to the default rather than raising. This runs
    while the gateway wires itself up, and `_wire_feedback` is not guarded, so
    a typo in one optional variable must not cost the deployment its feedback
    endpoint -- and an OverflowError from a pasted epoch timestamp must not
    cost it the boot.
    """
    raw = (os.environ.get(FEEDBACK_GRACE_ENV) or "").strip()
    if not raw:
        return timedelta(minutes=DEFAULT_GRACE_MINUTES)
    try:
        window = timedelta(minutes=int(raw))
    except (ValueError, OverflowError):
        window = None
    if window is None or window < timedelta(0):
        logger.warning(
            "%s must be a whole number of minutes, 0 or more; using %d",
            FEEDBACK_GRACE_ENV,
            DEFAULT_GRACE_MINUTES,
        )
        return timedelta(minutes=DEFAULT_GRACE_MINUTES)
    return window


class UnknownSession(LookupError):
    """A session id was supplied but the session manager does not know it."""


class FeedbackSessions(Protocol):
    """The lookups feedback needs, which both session managers provide."""

    def resolve_customer_session(self, session_id: str) -> Optional[TenantSessionKey]: ...

    def resolve_ended_session(
        self, session_id: str, *, within: timedelta
    ) -> Optional[TenantSessionKey]: ...

    def has_unscoped_session(self, session_id: str) -> bool: ...


class FeedbackService:
    def __init__(
        self,
        *,
        repository: FeedbackRepository,
        cipher: Any,
        tenant_resolver: TenantResolver,
        session_manager: FeedbackSessions,
        telemetry: Any,
        pseudonymizer: SessionPseudonymizer,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        grace_window: timedelta | None = None,
    ) -> None:
        self._repository = repository
        self._cipher = cipher
        self._tenant_resolver = tenant_resolver
        self._session_manager = session_manager
        self._telemetry = telemetry
        self._pseudonymizer = pseudonymizer
        self._clock = clock
        self._grace_window = (
            grace_window if grace_window is not None else _configured_grace_window()
        )

    async def submit(self, request: FeedbackSubmissionRequest) -> UUID:
        text = self._validated_text(request.improvements)
        reference, session_key = self._resolve_session(request.session_id)
        tenant_id = await self._tenant_resolver.resolve(request.session_id, session_key)

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
            tenant_ref=tenant_ref(tenant_id),
            feedback_ref=self._pseudonymizer.feedback_reference(feedback_id),
            translation_quality=request.translation_quality,
            performance=request.performance,
            usability=request.usability,
            net_promoter_score=request.net_promoter_score,
            form_version=request.form_version,
        )

        # Best-effort for real: the row is committed, so nothing from here on
        # may turn a stored submission into an error the caller can act on. A
        # 500 would put Retry in front of someone whose feedback was saved, and
        # the retry would store a second row that analytics counts again. A row
        # left `pending` is what the reconciler exists to drain.
        try:
            if result.outcome is ProbeOutcome.EMITTED:
                await self._repository.mark_analytics_delivered(feedback_id, tenant_id)
            elif result.outcome is ProbeOutcome.DISABLED:
                # Nothing will ever drain a backlog for an event type this
                # deployment does not emit, so it is not a backlog.
                await self._repository.mark_analytics_state(
                    feedback_id, AnalyticsState.NOT_APPLICABLE, tenant_id
                )
        except Exception as error:  # Reported, never raised.
            # Type name only: an asyncpg error carries the bound parameters.
            logger.warning("Feedback analytics state not recorded: %s", type(error).__name__)

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

    def _resolve_session(self, session_id: str | None) -> tuple[str, TenantSessionKey | None]:
        """The submission's pseudonymous reference, and its key when it has one.

        Resolved once and handed to the tenant resolver, rather than resolved
        again there: two independent resolutions can land on opposite sides of
        the grace window and file a tenant's feedback under the configured
        fallback instead.

        Three places a session can be. A legacy session sits under its bare id.
        A session opened through the tenant flow sits under a TenantSessionKey,
        and the bare id the browser sends reaches it through the join index --
        so checking the bare id alone answers 404 to every tenant's citizens.
        Once the conversation ends the store revokes that link, and the only
        remaining route is the tombstone behind resolve_ended_session, which a
        zero-length window skips rather than consults (#324).
        """
        if session_id is None:
            return MISSING_REFERENCE, None
        try:
            key = self._session_manager.resolve_customer_session(session_id)
            if key is None and self._grace_window > timedelta(0):
                key = self._session_manager.resolve_ended_session(
                    session_id, within=self._grace_window
                )
        except ValueError:
            # The store validates an id's shape before it looks anything up,
            # and the route catches nothing that would turn that into an
            # answer. An id no session could carry is an unknown session, not
            # a 500. `from None` keeps the submitted id out of the traceback.
            raise UnknownSession from None
        if key is None and not self._session_manager.has_unscoped_session(session_id):
            raise UnknownSession
        return self._pseudonymizer.reference(session_id), key


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
