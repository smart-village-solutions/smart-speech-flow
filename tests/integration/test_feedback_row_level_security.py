"""Row-level security, exercised as the roles the gateway actually connects as.

The policy in migration 001 is only as strong as the role that opens the
connection. Until 002 the gateway connected as the migration owner -- a
superuser, and therefore BYPASSRLS -- so a tenant-isolation assertion written
against that connection passed without the policy ever being consulted. Proven
against postgres:17.7-alpine: with `ssf.tenant_id` bound to one tenant, the
owner still saw both tenants' rows.

These tests connect as `ssf_feedback_app` and `ssf_feedback_maintenance` so the
policy is actually in the path. Three DSNs are needed because the roles are
deliberately unequal: only the owner can TRUNCATE, which is why it seeds and
cleans rather than being tested.
"""

import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import asyncpg
import pytest

from services.api_gateway.feedback.models import AnalyticsState, FeedbackRecord
from services.api_gateway.feedback.repository import PostgresFeedbackRepository

pytestmark = pytest.mark.integration

APP_DSN = os.environ.get("SSF_FEEDBACK_DATABASE_URL", "")
MAINTENANCE_DSN = os.environ.get("SSF_FEEDBACK_MAINTENANCE_DATABASE_URL", "")
OWNER_DSN = os.environ.get("SSF_FEEDBACK_OWNER_DATABASE_URL", "")

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"

_INSERT = """
INSERT INTO feedback (
    feedback_id, tenant_id, session_ref, translation_quality, performance,
    usability, net_promoter_score, improvements_ciphertext, form_version,
    retention_policy_version, consent_snapshot, analytics_event_id,
    analytics_state, created_at, expires_at
) VALUES ($1, $2, $3, 4, 5, 3, 9, NULL, 'v1', 'v1-12-months',
          '{}'::jsonb, $4, 'pending', $5, $6)
"""

_BIND = "SELECT set_config('ssf.tenant_id', $1, TRUE)"


def _record(**overrides: object) -> FeedbackRecord:
    now = datetime.now(timezone.utc)
    defaults = dict(
        feedback_id=uuid4(),
        tenant_id=TENANT_A,
        session_ref="a" * 32,
        translation_quality=4,
        performance=5,
        usability=3,
        net_promoter_score=9,
        improvements_ciphertext=b"\x01ciphertext-bytes",
        form_version="v1",
        retention_policy_version="v1-12-months",
        consent_snapshot={"form_version": "v1", "manifestation": "form_submission"},
        analytics_event_id=uuid4(),
        analytics_state=AnalyticsState.PENDING,
        created_at=now,
        expires_at=now + timedelta(days=365),
    )
    defaults.update(overrides)
    return FeedbackRecord(**defaults)


async def _seed(connection: asyncpg.Connection, tenant_id: str, *, expired: bool = False) -> UUID:
    """Insert one row as the owner, which bypasses the policy by design."""
    now = datetime.now(timezone.utc)
    expires_at = now - timedelta(days=1) if expired else now + timedelta(days=365)
    feedback_id = uuid4()
    await connection.execute(_INSERT, feedback_id, tenant_id, "a" * 32, uuid4(), now, expires_at)
    return feedback_id


@pytest.fixture
async def owner():
    connection = await asyncpg.connect(dsn=OWNER_DSN)
    await connection.execute("TRUNCATE feedback, feedback_deletion_audit")
    yield connection
    await connection.close()


@pytest.fixture
async def app_connection():
    connection = await asyncpg.connect(dsn=APP_DSN)
    yield connection
    await connection.close()


@pytest.fixture
async def maintenance_connection():
    connection = await asyncpg.connect(dsn=MAINTENANCE_DSN)
    yield connection
    await connection.close()


class TestTheRolesAreWhatTheyClaimToBe:
    """The privilege bits are the whole mechanism; assert them directly."""

    async def test_the_app_role_bypasses_nothing(self, app_connection) -> None:
        row = await app_connection.fetchrow(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )

        assert row["rolsuper"] is False
        assert row["rolbypassrls"] is False

    async def test_the_maintenance_role_bypasses_the_policy_without_being_a_superuser(
        self, maintenance_connection
    ) -> None:
        """It must see every tenant, and must not be able to do anything else."""
        row = await maintenance_connection.fetchrow(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )

        assert row["rolsuper"] is False
        assert row["rolbypassrls"] is True

    async def test_the_app_role_is_not_the_table_owner(self, app_connection) -> None:
        """An owner is exempt from its own policy unless RLS is forced."""
        owner = await app_connection.fetchval(
            "SELECT tableowner FROM pg_tables WHERE tablename = 'feedback'"
        )
        current = await app_connection.fetchval("SELECT current_user")

        assert owner != current


class TestTheTenantPathSeesOneTenant:
    async def test_an_unbound_connection_sees_no_rows(self, owner, app_connection) -> None:
        """current_setting returns NULL unbound, so the policy matches nothing."""
        await _seed(owner, TENANT_A)

        visible = await app_connection.fetchval("SELECT count(*) FROM feedback")

        assert visible == 0

    async def test_a_bound_connection_sees_only_its_own_tenant(self, owner, app_connection) -> None:
        await _seed(owner, TENANT_A)
        await _seed(owner, TENANT_B)

        async with app_connection.transaction():
            await app_connection.execute(_BIND, TENANT_A)
            tenants = await app_connection.fetch("SELECT DISTINCT tenant_id FROM feedback")

        assert [row["tenant_id"] for row in tenants] == [TENANT_A]

    async def test_another_tenants_row_is_invisible_even_by_its_own_id(
        self, owner, app_connection
    ) -> None:
        """A leaked identifier must not be enough to read the row."""
        foreign_id = await _seed(owner, TENANT_B)

        async with app_connection.transaction():
            await app_connection.execute(_BIND, TENANT_A)
            row = await app_connection.fetchrow(
                "SELECT feedback_id FROM feedback WHERE feedback_id = $1", foreign_id
            )

        assert row is None


class TestTheTenantPathCannotWriteOutsideItsTenant:
    async def test_an_insert_for_another_tenant_is_rejected(self, owner, app_connection) -> None:
        """With no WITH CHECK clause, Postgres reuses USING for inserts."""
        now = datetime.now(timezone.utc)

        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with app_connection.transaction():
                await app_connection.execute(_BIND, TENANT_A)
                await app_connection.execute(
                    _INSERT,
                    uuid4(),
                    TENANT_B,
                    "b" * 32,
                    uuid4(),
                    now,
                    now + timedelta(days=365),
                )

    async def test_the_app_role_cannot_delete_feedback(self, owner, app_connection) -> None:
        """Retention must not be reachable from a request path."""
        await _seed(owner, TENANT_A)

        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with app_connection.transaction():
                await app_connection.execute(_BIND, TENANT_A)
                await app_connection.execute("DELETE FROM feedback")


class TestTheTenantPathCanStillUpdateItsOwnRows:
    """An UPDATE the policy filters to nothing succeeds while doing nothing.

    `service.submit` marks the row delivered immediately after emitting. If that
    statement binds no tenant, the policy matches no rows, asyncpg reports
    success, and every submission stays `pending` forever -- so the reconciler
    re-emits all of them and gold's rating averages drift on every row.
    """

    async def test_marking_delivered_changes_the_stored_state(self, owner) -> None:
        repository = await PostgresFeedbackRepository.create(dsn=APP_DSN)
        record = _record()
        try:
            await repository.store(record)
            await repository.mark_analytics_delivered(record.feedback_id, TENANT_A)
        finally:
            await repository.close()

        state = await owner.fetchval(
            "SELECT analytics_state FROM feedback WHERE feedback_id = $1",
            record.feedback_id,
        )

        assert state == "delivered"

    async def test_marking_a_state_changes_the_stored_state(self, owner) -> None:
        repository = await PostgresFeedbackRepository.create(dsn=APP_DSN)
        record = _record()
        try:
            await repository.store(record)
            await repository.mark_analytics_state(
                record.feedback_id, AnalyticsState.NOT_APPLICABLE, TENANT_A
            )
        finally:
            await repository.close()

        state = await owner.fetchval(
            "SELECT analytics_state FROM feedback WHERE feedback_id = $1",
            record.feedback_id,
        )

        assert state == AnalyticsState.NOT_APPLICABLE.value

    async def test_another_tenants_row_cannot_be_marked(self, owner) -> None:
        """The tenant is the caller's, not the row's: a wrong pair changes nothing."""
        foreign_id = await _seed(owner, TENANT_B)
        repository = await PostgresFeedbackRepository.create(dsn=APP_DSN)
        try:
            await repository.mark_analytics_delivered(foreign_id, TENANT_A)
        finally:
            await repository.close()

        state = await owner.fetchval(
            "SELECT analytics_state FROM feedback WHERE feedback_id = $1", foreign_id
        )

        assert state == "pending"


class TestTheRepositoryStillWorksUnderTheAppRole:
    """The policy is worthless if it also breaks the submission it protects."""

    async def test_a_submission_is_stored_and_readable_within_its_tenant(self, owner) -> None:
        repository = await PostgresFeedbackRepository.create(dsn=APP_DSN)
        record = _record()
        try:
            await repository.store(record)

            async with repository._pool.acquire() as connection:  # noqa: SLF001
                async with connection.transaction():
                    await connection.execute(_BIND, TENANT_A)
                    stored = await connection.fetchval(
                        "SELECT count(*) FROM feedback WHERE feedback_id = $1",
                        record.feedback_id,
                    )
        finally:
            await repository.close()

        assert stored == 1


class TestMaintenanceSeesEveryTenant:
    async def test_pending_rows_from_every_tenant_are_claimed(self, owner) -> None:
        first = await _seed(owner, TENANT_A)
        second = await _seed(owner, TENANT_B)
        repository = await PostgresFeedbackRepository.create(dsn=MAINTENANCE_DSN)
        try:
            pending = await repository.claim_pending_analytics(limit=100)
        finally:
            await repository.close()

        claimed = {row.feedback_id for row in pending}
        assert {first, second} <= claimed

    async def test_expired_rows_from_every_tenant_are_deleted(self, owner) -> None:
        await _seed(owner, TENANT_A, expired=True)
        await _seed(owner, TENANT_B, expired=True)
        repository = await PostgresFeedbackRepository.create(dsn=MAINTENANCE_DSN)
        try:
            deleted = await repository.delete_expired(datetime.now(timezone.utc), limit=100)
        finally:
            await repository.close()

        assert len(deleted) == 2

    async def test_the_deletion_audit_records_both_tenants(self, owner) -> None:
        await _seed(owner, TENANT_A, expired=True)
        await _seed(owner, TENANT_B, expired=True)
        repository = await PostgresFeedbackRepository.create(dsn=MAINTENANCE_DSN)
        try:
            await repository.delete_expired(datetime.now(timezone.utc), limit=100)
        finally:
            await repository.close()

        tenants = await owner.fetch("SELECT DISTINCT tenant_id FROM feedback_deletion_audit")

        assert {row["tenant_id"] for row in tenants} == {TENANT_A, TENANT_B}
