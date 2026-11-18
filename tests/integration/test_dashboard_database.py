"""Real RLS dashboard composition, stable page joins and result-only reads."""

import os
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest

from services.api_gateway.dashboard import Dashboard
from services.api_gateway.dashboard_repository import DashboardRecords
from services.api_gateway.recording.repository import bind_tenant
from services.api_gateway.session_models import Session, SessionStatus
from services.api_gateway.session_pseudonym import SessionPseudonymizer
from tests.test_dashboard_overview import Sessions

pytestmark = pytest.mark.integration
NOW = datetime.now(timezone.utc)


@pytest.fixture
async def db():
    dsn = os.environ.get("SSF_RECORDING_OWNER_DATABASE_URL")
    if not dsn:
        pytest.skip("requires isolated recording postgres")
    conn = await asyncpg.connect(
        dsn, password=os.environ.get("SSF_RECORDING_OWNER_DATABASE_PASSWORD")
    )
    pool = await asyncpg.create_pool(
        os.environ["SSF_RECORDING_DATABASE_URL"],
        password=os.environ.get("SSF_RECORDING_DATABASE_PASSWORD"),
        min_size=1,
        max_size=2,
    )
    try:
        yield conn, DashboardRecords(pool)
    finally:
        await pool.close()
        await conn.close()


async def conversation(conn, tenant, sub, ref, start):
    cid = uuid.uuid4()
    await conn.execute(
        """INSERT INTO conversations(tenant_id,conversation_id,session_ref,employee_sub,
        legal_basis,timestamp_authority_url,started_at,retention_until,ended_at)
        VALUES($1,$2,$3,$4,'consent','https://tsa.invalid',$5,$6,$7)""",
        tenant,
        cid,
        ref,
        sub,
        start,
        NOW + timedelta(days=1),
        NOW,
    )
    return str(cid)


async def test_sql_combines_owned_sessions_and_recordings_without_duplicates_on_next_page(db):
    conn, records = db
    tenant = str(uuid.uuid4())
    pseudo = SessionPseudonymizer(key=b"dashboard-test")
    newer = Session(
        id="NEW",
        tenant_id=tenant,
        owner_ref="owner",
        created_at=NOW,
        status=SessionStatus.TERMINATED,
        terminated_at=NOW,
        customer_language="en",
    )
    older = Session(
        id="OLD",
        tenant_id=tenant,
        owner_ref="owner",
        created_at=NOW - timedelta(days=1),
        status=SessionStatus.TERMINATED,
        terminated_at=NOW,
    )
    cid = await conversation(conn, tenant, "alice", pseudo.recording_reference("NEW"), NOW)
    await conversation(conn, tenant, "colleague", "foreign", NOW)
    await conversation(conn, "other-" + tenant, "alice", "other-tenant", NOW)
    service = Dashboard(Sessions([newer, older]), records, pseudo)
    first = await service.conversations(
        tenant, "alice", "owner", frozenset({"ssf.recording.request"}), 1, None
    )
    assert [row["recording_id"] for row in first["items"]] == [cid]
    assert first["items"][0]["customer_language"] is None
    second = await service.conversations(
        tenant, "alice", "owner", frozenset({"ssf.recording.request"}), 1, first["next_cursor"]
    )
    assert [row["session_id"] for row in second["items"]] == ["OLD"]
    assert second["next_cursor"] is None


async def test_recording_query_does_not_return_expired_or_shredded_metadata(db):
    conn, records = db
    tenant = str(uuid.uuid4())
    cid = await conversation(conn, tenant, "alice", "expired", NOW)
    await conn.execute(
        "UPDATE conversations SET retention_until=$2 WHERE conversation_id=$1",
        uuid.UUID(cid),
        NOW - timedelta(seconds=1),
    )
    rows = await records.overview(tenant, "alice", {}, None, 50, False)
    assert rows == []


async def test_result_query_is_reviewer_bound_and_returns_only_completed_outcome(db):
    conn, records = db
    tenant = str(uuid.uuid4())
    cid = await conversation(conn, tenant, "alice", "result", NOW)
    vid = uuid.uuid4()
    # The final decision's signature/notes are deliberately present and must never leave this query.
    await conn.execute(
        """INSERT INTO verifications(tenant_id,verification_id,conversation_id,status,
        reviewer_sub,requested_by,requested_at,requester_key_version,reviewer_key_version,
        reviewer_fingerprint,directory_read_at)
        VALUES($1,$2,$3,'awaiting','bob','alice',$4,1,1,$5,$4)""",
        tenant,
        vid,
        uuid.UUID(cid),
        NOW,
        bytes(32),
    )
    assert await records.completed_result(tenant, "bob", str(vid)) is None
    # Closed-record invariants require valid complete values.
    await conn.execute(
        """UPDATE verifications SET status='approved',outcome='approved',
        notes_digest=$2,signature=$3,signer_key_version=1,decided_at=$4,
        reviewed_head=$2,reviewed_head_seq=1,permission_snapshot=ARRAY[]::text[]
        WHERE verification_id=$1""",
        vid,
        bytes(32),
        bytes(64),
        NOW,
    )
    result = await records.completed_result(tenant, "bob", str(vid))
    assert result["outcome"] == "approved"
    assert set(result) == {
        "verification_id",
        "status",
        "outcome",
        "requested_at",
        "decided_at",
        "requested_by_name",
    }
    assert await records.completed_result(tenant, "alice", str(vid)) is None
    assert await records.completed_result("another-" + tenant, "bob", str(vid)) is None


async def test_recorded_language_stays_hidden_when_recording_permission_is_removed(db):
    conn, records = db
    tenant = str(uuid.uuid4())
    pseudo = SessionPseudonymizer(key=b"privacy-test")
    owned = Session(
        id="RETAINED",
        tenant_id=tenant,
        owner_ref="owner",
        created_at=NOW,
        status=SessionStatus.TERMINATED,
        terminated_at=NOW,
        customer_language="en",
    )
    await conversation(conn, tenant, "alice", pseudo.recording_reference("RETAINED"), NOW)
    service = Dashboard(Sessions([owned]), records, pseudo)
    page = await service.conversations(tenant, "alice", "owner", frozenset(), 50, None)
    assert len(page["items"]) == 1
    assert page["items"][0]["language_visibility"] == "encrypted"
    assert page["items"][0]["customer_language"] is None
    assert page["items"][0]["actions"] == []


async def test_transfer_grant_is_listable_but_revoked_key_and_missing_permission_are_not(db):
    conn, records = db
    tenant = str(uuid.uuid4())
    cid = await conversation(conn, tenant, "someone", "transferred", NOW)
    kid = uuid.uuid4()
    await conn.execute(
        """INSERT INTO user_keys(tenant_id,user_sub,key_version,enc_pub,sig_pub,
        fingerprint,encrypted_private,created_at) VALUES($1,'alice',1,$2,$2,$3,$4,$5)""",
        tenant,
        bytes(65),
        bytes(32),
        bytes(48),
        NOW,
    )
    await conn.execute(
        "INSERT INTO conversation_keys VALUES($1,$2,$3,1,$4)", tenant, kid, uuid.UUID(cid), NOW
    )
    await conn.execute(
        """INSERT INTO key_wraps(tenant_id,key_id,recipient_kind,recipient_ref,
        blob,creator_ref,creator_signature,granted_at,recipient_version,recipient_fingerprint)
        VALUES($1,$2,'user','alice','{}','gateway',$3,$4,1,$5)""",
        tenant,
        kid,
        bytes(64),
        NOW,
        bytes(32),
    )
    await conn.execute(
        "INSERT INTO key_grants VALUES($1,$2,'alice',1,'transfer',$3)", tenant, kid, uuid.uuid4()
    )
    pseudo = SessionPseudonymizer(key=b"transfer-test")
    service = Dashboard(Sessions([]), records, pseudo)
    allowed = await service.conversations(
        tenant, "alice", "owner", frozenset({"ssf.recording.request"}), 50, None
    )
    assert [row["recording_id"] for row in allowed["items"]] == [cid]
    assert allowed["items"][0]["actions"] == ["open_recording"]
    unprivileged = await service.conversations(tenant, "alice", "owner", frozenset(), 50, None)
    assert unprivileged["items"] == []
    await conn.execute("UPDATE user_keys SET retired_at=$2 WHERE tenant_id=$1", tenant, NOW)
    revoked = await service.conversations(
        tenant, "alice", "owner", frozenset({"ssf.recording.request"}), 50, None
    )
    assert revoked["items"] == []
