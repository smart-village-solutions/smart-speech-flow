"""The authorised read path's behaviour, independent of HTTP and PostgreSQL.

Two things matter here and are tested rather than assumed: a disclosure is
always audited, and a record belonging to another tenant is indistinguishable
from one that does not exist.
"""

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from services.api_gateway.feedback.bundled_form import bundled_rules
from services.api_gateway.feedback.models import AnalyticsState, FeedbackRecord
from services.api_gateway.feedback.read import (
    FeedbackNotFound,
    FeedbackReadService,
)

TENANT = "tenant-kassel"
OTHER_TENANT = "tenant-other"
OPERATOR = "operator-1"
CREATED = datetime(2026, 9, 11, 10, 30, tzinfo=timezone.utc)
EXPIRES = datetime(2027, 9, 11, 10, 30, tzinfo=timezone.utc)


class FakeCipher:
    """Mirrors FeedbackCipher's AAD binding without the key material."""

    def encrypt(self, plaintext: str, *, feedback_id: UUID, tenant_id: str) -> bytes:
        return f"{feedback_id}|{tenant_id}|{plaintext}".encode()

    def decrypt(self, envelope: bytes, *, feedback_id: UUID, tenant_id: str) -> str:
        expected = f"{feedback_id}|{tenant_id}|".encode()
        if not envelope.startswith(expected):
            raise ValueError("feedback envelope failed authentication")
        return envelope[len(expected) :].decode()


BUNDLED_NUMBERS = {"translationQuality": 4, "performance": 5, "usability": 3, "recommendation": 9}


def _record(
    *,
    feedback_id=None,
    tenant_id=TENANT,
    improvements="More languages",
    text_answers=None,
    numeric_answers=None,
    form_snapshot=bundled_rules().snapshot,
    form_source="bundled",
    revision=None,
):
    """A row converted by migration 004 by default: legacy text, bundled form.

    `text_answers` makes it a v2 row instead, with a JSON envelope.
    """
    feedback_id = feedback_id or uuid4()
    cipher = FakeCipher()
    if text_answers is not None:
        plaintext, legacy = json.dumps(text_answers), False
    else:
        plaintext, legacy = improvements, improvements is not None
    ciphertext = (
        cipher.encrypt(plaintext, feedback_id=feedback_id, tenant_id=tenant_id)
        if plaintext is not None
        else None
    )
    return FeedbackRecord(
        feedback_id=feedback_id,
        tenant_id=tenant_id,
        session_ref="b" * 32,
        audience="guest",
        form_source=form_source,
        configuration_revision=revision,
        form_locale="en" if text_answers is not None else None,
        form_snapshot=form_snapshot,
        numeric_answers=dict(BUNDLED_NUMBERS if numeric_answers is None else numeric_answers),
        text_answers_ciphertext=ciphertext,
        text_answers_legacy=legacy,
        form_version="v1" if text_answers is None else "v2",
        retention_policy_version="v1-12-months",
        consent_snapshot={},
        analytics_event_id=uuid4(),
        analytics_state=AnalyticsState.DELIVERED,
        created_at=CREATED,
        expires_at=EXPIRES,
    )


class FakeReadRepository:
    def __init__(self, records=()):
        self.records = list(records)
        self.audited: list = []
        self.access_calls = 0

    async def list_records(self, *, tenant_id, limit, offset):
        visible = [r for r in self.records if r.tenant_id == tenant_id]
        return visible[offset : offset + limit]

    async def fetch_record(self, *, feedback_id, tenant_id):
        for record in self.records:
            if record.feedback_id == feedback_id and record.tenant_id == tenant_id:
                return record
        return None

    async def record_access(self, *, feedback_id, tenant_id, accessed_by, access_scope):
        self.access_calls += 1
        self.audited.append((feedback_id, tenant_id, accessed_by, access_scope))

    async def record_accesses(self, *, feedback_ids, tenant_id, accessed_by, access_scope):
        self.access_calls += 1
        for feedback_id in feedback_ids:
            self.audited.append((feedback_id, tenant_id, accessed_by, access_scope))


def _service(records=()):
    repository = FakeReadRepository(records)
    return FeedbackReadService(repository=repository, cipher=FakeCipher()), repository


@pytest.mark.asyncio
async def test_a_disclosure_writes_an_access_audit_row() -> None:
    record = _record()
    service, repository = _service([record])

    detail = await service.read_for_tenant(
        feedback_id=record.feedback_id, tenant_id=TENANT, accessed_by=OPERATOR
    )

    assert detail.improvements == "More languages"
    assert repository.audited == [(record.feedback_id, TENANT, OPERATOR, "detail")]


@pytest.mark.asyncio
async def test_another_tenants_record_is_not_found() -> None:
    record = _record(tenant_id=OTHER_TENANT)
    service, repository = _service([record])

    with pytest.raises(FeedbackNotFound):
        await service.read_for_tenant(
            feedback_id=record.feedback_id, tenant_id=TENANT, accessed_by=OPERATOR
        )


@pytest.mark.asyncio
async def test_a_refused_read_is_not_audited_as_a_disclosure() -> None:
    """Nothing was disclosed, so the audit must not claim otherwise."""
    record = _record(tenant_id=OTHER_TENANT)
    service, repository = _service([record])

    with pytest.raises(FeedbackNotFound):
        await service.read_for_tenant(
            feedback_id=record.feedback_id, tenant_id=TENANT, accessed_by=OPERATOR
        )

    assert repository.audited == []


@pytest.mark.asyncio
async def test_an_empty_improvement_field_reads_as_absent_not_empty() -> None:
    record = _record(improvements=None)
    service, _ = _service([record])

    detail = await service.read_for_tenant(
        feedback_id=record.feedback_id, tenant_id=TENANT, accessed_by=OPERATOR
    )

    assert detail.improvements is None
    assert detail.summary.has_improvements is False


@pytest.mark.asyncio
async def test_listing_returns_only_the_callers_tenant() -> None:
    mine, theirs = _record(), _record(tenant_id=OTHER_TENANT)
    service, _ = _service([mine, theirs])

    summaries = await service.list_for_tenant(
        tenant_id=TENANT, accessed_by=OPERATOR, limit=50, offset=0
    )

    assert [s.feedback_id for s in summaries] == [mine.feedback_id]


@pytest.mark.asyncio
async def test_listing_audits_every_record_it_returns() -> None:
    mine = _record()
    service, repository = _service([mine])

    await service.list_for_tenant(tenant_id=TENANT, accessed_by=OPERATOR, limit=50, offset=0)

    assert repository.audited == [(mine.feedback_id, TENANT, OPERATOR, "list")]


@pytest.mark.asyncio
async def test_an_unreadable_envelope_is_not_reported_as_empty_text() -> None:
    """A rotated or wrong key must not look like a submitter who wrote nothing."""
    from services.api_gateway.feedback.read import FeedbackTextUnreadable

    record = _record()
    tampered = FeedbackRecord(
        **{
            **{f: getattr(record, f) for f in record.__slots__},
            "text_answers_ciphertext": b"not-the-envelope-this-row-was-sealed-with",
        }
    )
    service, _ = _service([tampered])

    with pytest.raises(FeedbackTextUnreadable):
        await service.read_for_tenant(
            feedback_id=tampered.feedback_id, tenant_id=TENANT, accessed_by=OPERATOR
        )


@pytest.mark.asyncio
async def test_an_unreadable_record_is_still_audited() -> None:
    """Its existence was disclosed: the caller gets 500, not the 404 for absent.

    Auditing only after a successful decrypt leaves that disclosure unrecorded,
    which is the one thing feedback_access_audit exists to prevent.
    """
    from services.api_gateway.feedback.read import FeedbackTextUnreadable

    record = _record()
    tampered = FeedbackRecord(
        **{
            **{f: getattr(record, f) for f in record.__slots__},
            "text_answers_ciphertext": b"not-the-envelope-this-row-was-sealed-with",
        }
    )
    service, repository = _service([tampered])

    with pytest.raises(FeedbackTextUnreadable):
        await service.read_for_tenant(
            feedback_id=tampered.feedback_id, tenant_id=TENANT, accessed_by=OPERATOR
        )

    assert repository.audited == [(tampered.feedback_id, TENANT, OPERATOR, "detail")]


@pytest.mark.asyncio
async def test_a_listing_writes_its_audit_in_one_call() -> None:
    """Per-row writes take a pooled connection each: a 200-row page is 200
    round trips on a pool of 5."""
    records = [_record() for _ in range(5)]
    service, repository = _service(records)

    await service.list_for_tenant(tenant_id=TENANT, accessed_by=OPERATOR, limit=50, offset=0)

    assert repository.access_calls == 1
    assert len(repository.audited) == 5


@pytest.mark.asyncio
async def test_a_converted_row_reads_its_old_text_as_the_improvement_ideas() -> None:
    record = _record(improvements="Old text")
    service, _ = _service([record])

    detail = await service.read_for_tenant(
        feedback_id=record.feedback_id, tenant_id=TENANT, accessed_by=OPERATOR
    )

    assert detail.improvements == "Old text"
    assert detail.text_answers == {"improvementIdeas": "Old text"}


@pytest.mark.asyncio
async def test_a_v2_row_discloses_every_text_answer() -> None:
    record = _record(text_answers={"improvementIdeas": "Ideas", "notes": "Notes"})
    service, _ = _service([record])

    detail = await service.read_for_tenant(
        feedback_id=record.feedback_id, tenant_id=TENANT, accessed_by=OPERATOR
    )

    assert detail.text_answers == {"improvementIdeas": "Ideas", "notes": "Notes"}
    assert detail.improvements == "Ideas"
    assert detail.summary.has_improvements is True


@pytest.mark.asyncio
async def test_a_v2_row_without_improvement_ideas_has_no_improvements() -> None:
    record = _record(text_answers={"notes": "Notes"})
    service, _ = _service([record])

    detail = await service.read_for_tenant(
        feedback_id=record.feedback_id, tenant_id=TENANT, accessed_by=OPERATOR
    )

    assert detail.improvements is None
    assert detail.text_answers == {"notes": "Notes"}


@pytest.mark.asyncio
async def test_a_summary_carries_the_form_and_the_answers_by_id() -> None:
    snapshot = ({"id": "clarity", "type": "rating", "required": True, "min": 1, "max": 7},)
    record = _record(
        text_answers={},
        numeric_answers={"clarity": 6},
        form_snapshot=snapshot,
        form_source="studio",
        revision="sha256:abc",
    )
    service, _ = _service([record])

    (summary,) = await service.list_for_tenant(
        tenant_id=TENANT, accessed_by=OPERATOR, limit=50, offset=0
    )

    assert summary.audience == "guest"
    assert summary.form_source == "studio"
    assert summary.configuration_revision == "sha256:abc"
    assert summary.locale == "en"
    assert summary.numeric_answers == {"clarity": 6}
    assert summary.form_snapshot == list(snapshot)
    assert (
        summary.translation_quality,
        summary.performance,
        summary.usability,
        summary.net_promoter_score,
    ) == (None, None, None, None)


@pytest.mark.asyncio
async def test_a_summary_keeps_the_four_legacy_ratings_when_their_ids_are_answered() -> None:
    record = _record()
    service, _ = _service([record])

    (summary,) = await service.list_for_tenant(
        tenant_id=TENANT, accessed_by=OPERATOR, limit=50, offset=0
    )

    assert (
        summary.translation_quality,
        summary.performance,
        summary.usability,
        summary.net_promoter_score,
    ) == (4, 5, 3, 9)


@pytest.mark.asyncio
async def test_a_malformed_text_envelope_is_unreadable_not_empty() -> None:
    from services.api_gateway.feedback.read import FeedbackTextUnreadable

    record = _record(improvements=None)
    sealed = FakeCipher().encrypt(
        "[1, 2]", feedback_id=record.feedback_id, tenant_id=record.tenant_id
    )
    broken = FeedbackRecord(
        **{**{f: getattr(record, f) for f in record.__slots__}, "text_answers_ciphertext": sealed}
    )
    service, _ = _service([broken])

    with pytest.raises(FeedbackTextUnreadable):
        await service.read_for_tenant(
            feedback_id=broken.feedback_id, tenant_id=TENANT, accessed_by=OPERATOR
        )


@pytest.mark.asyncio
async def test_a_legacy_field_stays_null_when_its_id_was_asked_on_another_scale() -> None:
    """v1 readers take translation_quality as 1-5 stars; a 0-10 answer is not one."""
    snapshot = tuple(
        (
            {**question, "type": "scale", "min": 0, "max": 10}
            if question["id"] == "translationQuality"
            else question
        )
        for question in bundled_rules().snapshot
    )
    record = _record(
        text_answers={},
        form_snapshot=snapshot,
        numeric_answers={**BUNDLED_NUMBERS, "translationQuality": 9},
    )
    service, _ = _service([record])

    (summary,) = await service.list_for_tenant(
        tenant_id=TENANT, accessed_by=OPERATOR, limit=50, offset=0
    )

    assert summary.translation_quality is None
    assert summary.performance == 5
    assert summary.numeric_answers["translationQuality"] == 9
