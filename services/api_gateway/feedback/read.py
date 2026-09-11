"""The authorised read path over stored feedback.

Separate from FeedbackService, which only ever writes. This is the one place
that turns `improvements_ciphertext` back into text, so it is also the one
place that has to record an access audit row for doing so.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FeedbackSummary:
    """One row as Studio may list it: ratings and metadata, never free text.

    `has_improvements` reports that text exists without disclosing it, so a
    list view can show which records are worth opening -- and opening one is
    the act that gets audited.
    """

    feedback_id: UUID
    session_ref: str
    translation_quality: int
    performance: int
    usability: int
    net_promoter_score: int
    has_improvements: bool
    form_version: str
    analytics_state: str
    created_at: datetime
    expires_at: datetime


class FeedbackNotFound(LookupError):
    """No record with that id is visible to this tenant.

    One exception for "does not exist" and "belongs to another tenant", so a
    caller cannot use the read path to discover which ids are real elsewhere.
    """


@dataclass(frozen=True, slots=True)
class FeedbackDetail:
    """One record with its free text decrypted, for an audited disclosure."""

    summary: FeedbackSummary
    improvements: str | None


class FeedbackTextUnreadable(RuntimeError):
    """The record exists but its envelope did not authenticate.

    Distinct from "no text": a wrong or rotated key must not be reported to an
    operator as an empty improvement field, which would read as the submitter
    having written nothing.
    """


class FeedbackReadService:
    """Read stored feedback for one tenant, auditing what it discloses."""

    def __init__(self, *, repository: Any, cipher: Any) -> None:
        self._repository = repository
        self._cipher = cipher

    async def list_for_tenant(
        self, *, tenant_id: str, accessed_by: str, limit: int, offset: int
    ) -> list[FeedbackSummary]:
        records = await self._repository.list_records(
            tenant_id=tenant_id, limit=limit, offset=offset
        )
        summaries = [_summarise(record) for record in records]
        if summaries:
            # One write, not one per row: record_access takes a pooled
            # connection each time, and a full page on a pool of five would
            # otherwise be two hundred round trips for a single request.
            await self._repository.record_accesses(
                feedback_ids=[summary.feedback_id for summary in summaries],
                tenant_id=tenant_id,
                accessed_by=accessed_by,
                access_scope="list",
            )
        return summaries

    async def read_for_tenant(
        self, *, feedback_id: UUID, tenant_id: str, accessed_by: str
    ) -> FeedbackDetail:
        record = await self._repository.fetch_record(feedback_id=feedback_id, tenant_id=tenant_id)
        if record is None:
            # Audited deliberately nowhere: nothing was disclosed, and a row
            # here would let a caller write audit entries for ids they cannot
            # read.
            raise FeedbackNotFound("no such feedback record for this tenant")

        # Audited before the decrypt, not after. Reaching this line is the
        # disclosure: the caller already learns the record exists, because an
        # unreadable envelope answers 500 where an absent record answers 404.
        # Auditing afterwards would leave that disclosure unrecorded. An audit
        # that cannot be written still raises here, so nothing is disclosed
        # without a record of it.
        await self._repository.record_access(
            feedback_id=record.feedback_id,
            tenant_id=tenant_id,
            accessed_by=accessed_by,
            access_scope="detail",
        )
        improvements = self._decrypt(record)
        return FeedbackDetail(summary=_summarise(record), improvements=improvements)

    def _decrypt(self, record: Any) -> str | None:
        if record.improvements_ciphertext is None:
            return None
        try:
            return self._cipher.decrypt(
                record.improvements_ciphertext,
                feedback_id=record.feedback_id,
                tenant_id=record.tenant_id,
            )
        except ValueError as error:
            # Type name only, matching the repository: the exception string can
            # carry envelope bytes.
            logger.warning("Feedback text could not be read: %s", type(error).__name__)
            raise FeedbackTextUnreadable("the stored text did not authenticate") from None


def _summarise(record: Any) -> FeedbackSummary:
    return FeedbackSummary(
        feedback_id=record.feedback_id,
        session_ref=record.session_ref,
        translation_quality=record.translation_quality,
        performance=record.performance,
        usability=record.usability,
        net_promoter_score=record.net_promoter_score,
        has_improvements=record.improvements_ciphertext is not None,
        form_version=record.form_version,
        analytics_state=(
            record.analytics_state.value
            if hasattr(record.analytics_state, "value")
            else record.analytics_state
        ),
        created_at=record.created_at,
        expires_at=record.expires_at,
    )
