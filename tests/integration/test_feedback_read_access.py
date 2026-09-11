"""The authorised read path, exercised as the role it actually connects as.

The point of a third role is that tenant isolation on reads is enforced by
PostgreSQL rather than by a WHERE clause someone could forget. These tests
connect as `ssf_feedback_reader`, so migration 001's policy is in the path of
every read below -- and a bug that dropped the tenant from the query would show
up here as another tenant's row appearing, not as a passing test.
"""

import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import asyncpg
import pytest

from services.api_gateway.feedback.repository import PostgresFeedbackReadRepository

pytestmark = pytest.mark.integration

READER_DSN = os.environ.get("SSF_FEEDBACK_READER_DATABASE_URL", "")
OWNER_DSN = os.environ.get("SSF_FEEDBACK_OWNER_DATABASE_URL", "")
READER_PASSWORD = os.environ.get("SSF_FEEDBACK_READER_DATABASE_PASSWORD") or None
OWNER_PASSWORD = os.environ.get("SSF_FEEDBACK_OWNER_DATABASE_PASSWORD") or None

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"

_INSERT = """
INSERT INTO feedback (
    feedback_id, tenant_id, session_ref, translation_quality, performance,
    usability, net_promoter_score, improvements_ciphertext, form_version,
    retention_policy_version, consent_snapshot, analytics_event_id,
    analytics_state, created_at, expires_at
) VALUES ($1, $2, $3, 4, 5, 3, 9, $4, 'v1', 'v1-12-months',
          '{}'::jsonb, $5, 'delivered', $6, $7)
"""


async def _seed(connection, tenant_id, *, ciphertext=b"\x01sealed") -> UUID:
    now = datetime.now(timezone.utc)
    feedback_id = uuid4()
    await connection.execute(
        _INSERT,
        feedback_id,
        tenant_id,
        "a" * 32,
        ciphertext,
        uuid4(),
        now,
        now + timedelta(days=365),
    )
    return feedback_id


@pytest.fixture
async def owner():
    connection = await asyncpg.connect(dsn=OWNER_DSN, password=OWNER_PASSWORD)
    await connection.execute("TRUNCATE feedback, feedback_access_audit")
    yield connection
    await connection.close()


@pytest.fixture
async def reader_connection():
    connection = await asyncpg.connect(dsn=READER_DSN, password=READER_PASSWORD)
    yield connection
    await connection.close()


@pytest.fixture
async def repository():
    repo = await PostgresFeedbackReadRepository.create(dsn=READER_DSN, password=READER_PASSWORD)
    yield repo
    await repo.close()


class TestTheReadRoleIsWhatItClaimsToBe:
    async def test_the_read_role_bypasses_nothing(self, reader_connection) -> None:
        """BYPASSRLS here would make every tenant assertion below meaningless."""
        row = await reader_connection.fetchrow(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )

        assert row["rolsuper"] is False
        assert row["rolbypassrls"] is False

    async def test_the_read_role_cannot_write_feedback(self, owner, reader_connection) -> None:
        """A read path that can alter a record is not a read path."""
        feedback_id = await _seed(owner, TENANT_A)
        await reader_connection.execute("SELECT set_config('ssf.tenant_id', $1, TRUE)", TENANT_A)

        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await reader_connection.execute(
                "UPDATE feedback SET usability = 1 WHERE feedback_id = $1", feedback_id
            )

    async def test_the_read_role_cannot_delete_feedback(self, owner, reader_connection) -> None:
        """Withdrawal stays out of this role until #318 gives it its own route."""
        feedback_id = await _seed(owner, TENANT_A)
        await reader_connection.execute("SELECT set_config('ssf.tenant_id', $1, TRUE)", TENANT_A)

        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await reader_connection.execute(
                "DELETE FROM feedback WHERE feedback_id = $1", feedback_id
            )


class TestOneTenantCannotReadAnother:
    async def test_listing_returns_only_the_bound_tenants_rows(self, owner, repository) -> None:
        mine = await _seed(owner, TENANT_A)
        await _seed(owner, TENANT_B)

        records = await repository.list_records(tenant_id=TENANT_A, limit=50, offset=0)

        assert [record.feedback_id for record in records] == [mine]

    async def test_another_tenants_record_is_invisible_by_id(self, owner, repository) -> None:
        """The id is real and the row exists; the policy is what hides it."""
        theirs = await _seed(owner, TENANT_B)

        record = await repository.fetch_record(feedback_id=theirs, tenant_id=TENANT_A)

        assert record is None

    async def test_a_record_is_visible_to_its_own_tenant(self, owner, repository) -> None:
        """The negative above must not be passing because reads return nothing."""
        mine = await _seed(owner, TENANT_A)

        record = await repository.fetch_record(feedback_id=mine, tenant_id=TENANT_A)

        assert record is not None
        assert record.improvements_ciphertext == b"\x01sealed"


class TestTheAccessAuditIsWritable:
    async def test_a_disclosure_is_recorded(self, owner, repository) -> None:
        feedback_id = await _seed(owner, TENANT_A)

        await repository.record_access(
            feedback_id=feedback_id,
            tenant_id=TENANT_A,
            accessed_by="operator-1",
            access_scope="detail",
        )

        row = await owner.fetchrow(
            "SELECT tenant_id, accessed_by, access_scope FROM feedback_access_audit"
            " WHERE feedback_id = $1",
            feedback_id,
        )
        assert row["tenant_id"] == TENANT_A
        assert row["accessed_by"] == "operator-1"
        assert row["access_scope"] == "detail"
