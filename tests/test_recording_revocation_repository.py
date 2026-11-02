"""PostgresRevocations over a scripted connection, for the unit run (spec §10.7)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from services.api_gateway.recording.repository import RecordingStorageUnavailable
from services.api_gateway.recording.revocation_repository import PostgresRevocations
from tests.test_recording_archive_access_repository import ScriptedConnection, ScriptedPool

TENANT = "tenant-a"
NOW = datetime(2026, 11, 3, 3, 0, tzinfo=timezone.utc)
CONVERSATION, VERIFICATION, KEY = (str(uuid.uuid4()) for _ in range(3))


def repository(answers):
    connection = ScriptedConnection(answers)
    return PostgresRevocations(ScriptedPool(connection)), connection


def audits(connection) -> int:
    return sum("INSERT INTO audit_events" in call for call in connection.calls)


async def test_claims_finishes_and_last_success():
    repo, connection = repository(
        {"INSERT INTO revocation_runs": date(2026, 11, 3), "max(finished_at)": NOW}
    )
    assert await repo.claim(TENANT, date(2026, 11, 3), NOW, timedelta(hours=6)) is True
    await repo.finish(TENANT, date(2026, 11, 3), "done", NOW)
    assert await repo.owed_since(TENANT) == NOW
    taken, _ = repository({})
    assert await taken.claim(TENANT, date(2026, 11, 3), NOW, timedelta(hours=6)) is False


async def test_grants_and_holders_are_read():
    repo, _ = repository(
        {
            "FROM user_keys WHERE retired_at IS NULL": [{"user_sub": "alice"}],
            "SELECT v.verification_id, v.conversation_id, v.reviewer_sub": [
                {
                    "verification_id": uuid.UUID(VERIFICATION),
                    "conversation_id": uuid.UUID(CONVERSATION),
                    "reviewer_sub": "rita",
                    "directory_read_at": NOW,
                }
            ],
            "w.creator_ref = w.recipient_ref ORDER BY": [
                {"conversation_id": uuid.UUID(CONVERSATION), "recipient_ref": "sam"}
            ],
            "SELECT DISTINCT c.conversation_id FROM": [
                {"conversation_id": uuid.UUID(CONVERSATION)}
            ],
        }
    )
    assert await repo.key_holders(TENANT) == {"alice"}
    grants = await repo.grants(TENANT, NOW)
    assert grants.assignments[0].reviewer_sub == "rita"
    assert grants.recovered == ((CONVERSATION, "sam"),) and grants.orphaned == (CONVERSATION,)


async def test_a_revoke_withdraws_drafts_first_deletes_and_audits():
    repo, connection = repository(
        {
            "ORDER BY verification_id FOR UPDATE": [
                {"verification_id": uuid.UUID(VERIFICATION), "reviewer_sub": "rita"}
            ],
            "RETURNING w.key_id, w.recipient_ref": [
                {"key_id": uuid.UUID(KEY), "recipient_ref": "sam"}
            ],
            "SELECT DISTINCT w.recipient_ref": [{"recipient_ref": "rita"}],
            "RETURNING w.key_id": [{"key_id": uuid.UUID(KEY)}],
        }
    )

    deleted = await repo.revoke(TENANT, CONVERSATION, [VERIFICATION], ["sam"], "system", NOW)

    assert deleted == 2
    drafts = next(
        i for i, c in enumerate(connection.calls) if "DELETE FROM verification_notes" in c
    )
    withdrawn = next(
        i for i, c in enumerate(connection.calls) if "UPDATE verifications SET status" in c
    )
    assert drafts < withdrawn
    assert audits(connection) == 3  # one withdrawal and two revoked wraps


async def test_a_revoke_without_records_only_sweeps_and_a_skip_is_audited():
    repo, connection = repository({})
    assert await repo.revoke(TENANT, CONVERSATION, [], [], "system", NOW) == 0
    assert not any("UPDATE verifications SET status" in call for call in connection.calls)
    await repo.skipped(TENANT, "bound", date(2026, 11, 3), NOW, "system")
    assert audits(connection) == 1


async def test_a_database_that_cannot_answer_is_storage_unavailable():
    with pytest.raises(RecordingStorageUnavailable):
        await PostgresRevocations(ScriptedPool(None)).key_holders(TENANT)
