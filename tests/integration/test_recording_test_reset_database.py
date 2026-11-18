"""Reset only unique fixture tenants in a separately provisioned test database."""

import uuid

import pytest

from services.api_gateway.recording.reset_legacy_test_data import ResetRefusedError, reset
from tests.integration.test_dashboard_database import NOW, conversation, db

pytestmark = pytest.mark.integration


async def test_explicit_test_reset_keeps_other_tenant_and_audit(db):
    conn, _ = db
    tenant, other = str(uuid.uuid4()), str(uuid.uuid4())
    await conn.execute("INSERT INTO recording_protocol VALUES($1,1)", tenant)
    cid = await conversation(conn, tenant, "alice", "legacy-test", NOW)
    other_cid = await conversation(conn, other, "bob", "other-test", NOW)
    database = await conn.fetchval("SELECT current_database()")
    plan = await reset(
        conn, database=database, tenant=tenant, storage_target="test://isolated-no-objects"
    )
    assert plan["applied"] is False
    assert plan["tables"]["conversations"]["count"] == 1
    assert (
        await conn.fetchval(
            "SELECT count(*) FROM conversations WHERE conversation_id=$1", uuid.UUID(cid)
        )
        == 1
    )
    with pytest.raises(ResetRefusedError):
        await reset(
            conn,
            database=database,
            tenant=tenant,
            storage_target="test://isolated-no-objects",
            apply=True,
        )
    answer = await reset(
        conn,
        database=database,
        tenant=tenant,
        storage_target="test://isolated-no-objects",
        apply=True,
        writers_stopped=True,
        storage_cleared=True,
        confirmation=f'{database}:{tenant}:{plan["digest"]}',
    )
    assert answer["applied"] is True
    assert (
        await conn.fetchval(
            "SELECT count(*) FROM conversations WHERE conversation_id=$1", uuid.UUID(cid)
        )
        == 0
    )
    assert (
        await conn.fetchval(
            "SELECT count(*) FROM conversations WHERE conversation_id=$1", uuid.UUID(other_cid)
        )
        == 1
    )
    assert (
        await conn.fetchval("SELECT generation FROM recording_protocol WHERE tenant_id=$1", tenant)
        == 2
    )
    assert (
        await conn.fetchval(
            "SELECT count(*) FROM audit_events WHERE tenant_id=$1 AND event_type='recording.protocol.test_reset'",
            tenant,
        )
        == 1
    )


async def test_inventory_change_blocks_test_reset_and_rolls_back_trigger_state(db):
    conn, _ = db
    tenant = str(uuid.uuid4())
    await conn.execute("INSERT INTO recording_protocol VALUES($1,1)", tenant)
    database = await conn.fetchval("SELECT current_database()")
    plan = await reset(conn, database=database, tenant=tenant, storage_target="test://empty")
    await conversation(conn, tenant, "alice", "changed", NOW)
    with pytest.raises(ResetRefusedError):
        await reset(
            conn,
            database=database,
            tenant=tenant,
            storage_target="test://empty",
            apply=True,
            writers_stopped=True,
            storage_cleared=True,
            confirmation=f'{database}:{tenant}:{plan["digest"]}',
        )
    assert await conn.fetchval("SELECT count(*) FROM conversations WHERE tenant_id=$1", tenant) == 1
    assert (
        await conn.fetchval(
            "SELECT tgenabled::text FROM pg_trigger WHERE tgname='verification_notes_in_review'"
        )
        == "O"
    )
