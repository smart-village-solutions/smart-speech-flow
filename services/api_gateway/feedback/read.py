"""The authorised read path over stored feedback.

Separate from FeedbackService, which only ever writes. This is the one place
that turns `text_answers_ciphertext` back into text, so it is also the one
place that has to record an access audit row for doing so.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from . import bundled_form
from .text_answers import LEGACY_TEXT_ID, open_text_answers

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FeedbackSummary:
    """One row as Studio may list it: numbers and metadata, never free text.

    `has_improvements` reports that any text answer exists without disclosing
    it, so a list view can show which records are worth opening -- and opening
    one is the act that gets audited. The four rating fields predate answers
    by question id; each is filled when its bundled id was answered.
    """

    feedback_id: UUID
    session_ref: str
    translation_quality: int | None
    performance: int | None
    usability: int | None
    net_promoter_score: int | None
    has_improvements: bool
    form_version: str
    analytics_state: str
    created_at: datetime
    expires_at: datetime
    audience: str
    form_source: str
    configuration_revision: str | None
    locale: str | None
    numeric_answers: dict[str, int]
    form_snapshot: list[dict[str, Any]]


class FeedbackNotFound(LookupError):
    """No record with that id is visible to this tenant.

    One exception for "does not exist" and "belongs to another tenant", so a
    caller cannot use the read path to discover which ids are real elsewhere.
    """


@dataclass(frozen=True, slots=True)
class FeedbackDetail:
    """One record with its free text decrypted, for an audited disclosure.

    `improvements` is the `improvementIdeas` answer, kept for readers of the
    v1 shape; `text_answers` holds every text answer by question id.
    """

    summary: FeedbackSummary
    improvements: str | None
    text_answers: dict[str, str]


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
        text_answers = self._decrypt(record)
        return FeedbackDetail(
            summary=_summarise(record),
            improvements=text_answers.get(LEGACY_TEXT_ID),
            text_answers=text_answers,
        )

    def _decrypt(self, record: Any) -> dict[str, str]:
        try:
            return open_text_answers(
                self._cipher,
                record.text_answers_ciphertext,
                legacy=record.text_answers_legacy,
                feedback_id=record.feedback_id,
                tenant_id=record.tenant_id,
            )
        except ValueError as error:
            # Type name only, matching the repository: the exception string can
            # carry envelope bytes.
            logger.warning("Feedback text could not be read: %s", type(error).__name__)
            raise FeedbackTextUnreadable("the stored text did not authenticate") from None


def _summarise(record: Any) -> FeedbackSummary:
    numbers = record.numeric_answers
    return FeedbackSummary(
        feedback_id=record.feedback_id,
        session_ref=record.session_ref,
        translation_quality=_legacy(bundled_form.TRANSLATION_QUALITY, record),
        performance=_legacy(bundled_form.PERFORMANCE, record),
        usability=_legacy(bundled_form.USABILITY, record),
        net_promoter_score=_legacy(bundled_form.RECOMMENDATION, record),
        has_improvements=record.text_answers_ciphertext is not None,
        form_version=record.form_version,
        analytics_state=(
            record.analytics_state.value
            if hasattr(record.analytics_state, "value")
            else record.analytics_state
        ),
        created_at=record.created_at,
        expires_at=record.expires_at,
        audience=record.audience,
        form_source=record.form_source,
        configuration_revision=record.configuration_revision,
        locale=record.form_locale,
        numeric_answers=dict(numbers),
        form_snapshot=list(record.form_snapshot),
    )


def _legacy(question_id: str, record: Any) -> int | None:
    """A v1 field means its bundled range, so a form that asked differently leaves it null."""
    return bundled_form.legacy_rating(question_id, record.numeric_answers, record.form_snapshot)
