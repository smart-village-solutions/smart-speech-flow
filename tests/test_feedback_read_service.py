"""The authorised read path's behaviour, independent of HTTP and PostgreSQL.

Two things matter here and are tested rather than assumed: a disclosure is
always audited, and a record belonging to another tenant is indistinguishable
from one that does not exist.
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

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


def _record(*, feedback_id=None, tenant_id=TENANT, improvements="More languages"):
    feedback_id = feedback_id or uuid4()
    ciphertext = (
        FakeCipher().encrypt(improvements, feedback_id=feedback_id, tenant_id=tenant_id)
        if improvements is not None
        else None
    )
    return FeedbackRecord(
        feedback_id=feedback_id,
        tenant_id=tenant_id,
        session_ref="b" * 32,
        translation_quality=4,
        performance=5,
        usability=3,
        net_promoter_score=9,
        improvements_ciphertext=ciphertext,
        form_version="v1",
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

    async def list_records(self, *, tenant_id, limit, offset):
        visible = [r for r in self.records if r.tenant_id == tenant_id]
        return visible[offset : offset + limit]

    async def fetch_record(self, *, feedback_id, tenant_id):
        for record in self.records:
            if record.feedback_id == feedback_id and record.tenant_id == tenant_id:
                return record
        return None

    async def record_access(self, *, feedback_id, tenant_id, accessed_by, access_scope):
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
            "improvements_ciphertext": b"not-the-envelope-this-row-was-sealed-with",
        }
    )
    service, _ = _service([tampered])

    with pytest.raises(FeedbackTextUnreadable):
        await service.read_for_tenant(
            feedback_id=tampered.feedback_id, tenant_id=TENANT, accessed_by=OPERATOR
        )
