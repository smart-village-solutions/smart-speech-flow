"""The nightly revocation check against a real PostgreSQL (spec §10.7; migration 011)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from services.api_gateway.recording.revocation import RevocationCheck, run_due
from services.api_gateway.recording.revocation_repository import PostgresRevocations
from tests.integration.test_recording_verification_database import (  # noqa: F401 - fixtures
    NOW,
    SNAPSHOT,
    TENANT,
    _assigned,
    _consent,
    _ended,
    _granted,
    _key,
    _no_keys,
    _recovered,
    access,
    archive,
    owner,
    verifications,
)
from tests.recording_verification_world import directory

pytestmark = pytest.mark.integration
REVIEW = ["ssf.recording.review"]
SUPERVISE = ["ssf.recording.supervise"]


class Studio:
    def __init__(self, answer) -> None:
        self.answer = answer

    async def snapshot(self, tenant_id, correlation_id):
        return self.answer


async def _no_sleep(seconds):
    return None


@pytest.fixture
async def revocations(archive):
    return PostgresRevocations(archive._pool)


def _check(revocations, *users, answer="given"):
    studio = Studio(directory(*users, tenant_id=TENANT) if answer == "given" else answer)
    return RevocationCheck(
        revocations, studio, clock=lambda: NOW + timedelta(hours=1), sleep=_no_sleep
    )


async def _events(owner):
    rows = await owner.fetch(
        "SELECT actor_sub, event_type, object_ref FROM audit_events ORDER BY seq"
    )
    return [(r["actor_sub"], r["event_type"], r["object_ref"]) for r in rows]


async def test_a_reviewer_removed_from_the_directory_loses_access_in_one_run(
    archive, owner, verifications, revocations
):
    """AC4: the record is withdrawn, the wraps go, and the reviewer opens nothing more."""
    cid, key_id, row = await _assigned(archive, owner, verifications)
    head = await _consent(owner, cid)
    await verifications.start(TENANT, "rita", row.verification_id, head["seq"], SNAPSHOT, NOW)

    outcome = await _check(revocations, ("alice", REVIEW)).run_tenant(TENANT, "c")

    assert outcome == "done"
    assert await owner.fetchval("SELECT status FROM verifications") == "withdrawn"
    assert await owner.fetchval("SELECT close_reason FROM verifications") == "permission_revoked"
    assert await owner.fetchval("SELECT count(*) FROM key_wraps WHERE recipient_ref = 'rita'") == 0
    assert await owner.fetchval("SELECT count(*) FROM key_wraps WHERE recipient_ref = 'alice'") == 1
    assert (
        await verifications.open_review(TENANT, "rita", row.verification_id, NOW, reviewer=True)
        is None
    )
    events = await _events(owner)
    assert ("system", "recording.verification.withdrawn.permission_revoked", row.ref) in events
    assert ("system", "key_wrap.revoked", f"{key_id}:rita") in events


async def test_a_reviewer_still_in_the_directory_keeps_the_assignment(
    archive, owner, verifications, revocations
):
    await _assigned(archive, owner, verifications)
    assert (
        await _check(revocations, ("alice", REVIEW), ("rita", REVIEW)).run_tenant(TENANT, "c")
        == "done"
    )
    assert await owner.fetchval("SELECT status FROM verifications") == "awaiting"
    assert await owner.fetchval("SELECT count(*) FROM key_wraps WHERE recipient_ref = 'rita'") == 1


async def test_a_supervisor_without_supervise_loses_recovered_wraps_only(
    archive, owner, verifications, revocations
):
    conversation, key_id, _ = await _ended(archive, owner)
    await _key(owner, "alice")
    await _recovered(owner, conversation, key_id, requester="sam")
    await _recovered(owner, conversation, key_id, requester="sven")

    outcome = await _check(revocations, ("alice", REVIEW), ("sven", SUPERVISE)).run_tenant(
        TENANT, "c"
    )

    assert outcome == "done"
    remaining = {
        r["recipient_ref"]
        for r in await owner.fetch(
            "SELECT recipient_ref FROM key_wraps WHERE recipient_kind = 'user'"
        )
    }
    assert remaining == {"alice", "sven"}
    assert (
        await owner.fetchval("SELECT count(*) FROM key_wraps WHERE recipient_kind = 'recovery'")
        == 1
    )


async def test_an_orphaned_grant_is_swept_and_the_employees_own_never_touched(
    archive, owner, verifications, revocations
):
    conversation, key_id, _ = await _ended(archive, owner)
    await _key(owner, "alice")
    await _granted(owner, key_id, "rita", "alice")  # no assignment keeps it

    assert (
        await _check(revocations, ("bob", REVIEW), ("alice", ["ssf.recording.request"])).run_tenant(
            TENANT, "c"
        )
        == "done"
    )

    assert {
        r["recipient_ref"]
        for r in await owner.fetch(
            "SELECT recipient_ref FROM key_wraps WHERE recipient_kind = 'user'"
        )
    } == {"alice"}


@pytest.mark.parametrize("answer", [None, "empty"])
async def test_a_failed_or_empty_directory_deletes_nothing(
    archive, owner, verifications, revocations, answer
):
    await _assigned(archive, owner, verifications)
    studio_answer = None if answer is None else directory(tenant_id=TENANT)

    outcome = await _check(revocations, answer=studio_answer).run_tenant(TENANT, "c")

    assert outcome in {"skipped_unreadable", "skipped_implausible"}
    assert await owner.fetchval("SELECT status FROM verifications") == "awaiting"
    assert await owner.fetchval("SELECT count(*) FROM key_wraps WHERE recipient_ref = 'rita'") == 1
    assert (await _events(owner))[-1][1].startswith("recording.revocation.skipped.")


async def test_a_run_is_claimed_once_a_day_and_reclaimed_after_six_hours(
    owner, revocations, archive
):
    day = date(2026, 11, 3)
    assert await revocations.owed_since(TENANT) is None
    assert await revocations.claim(TENANT, day, NOW, timedelta(hours=6)) is True
    assert (
        await revocations.claim(TENANT, day, NOW + timedelta(hours=1), timedelta(hours=6)) is False
    )
    assert await revocations.owed_since(TENANT) == NOW  # never succeeded: owed since its first run
    assert (
        await revocations.claim(TENANT, day, NOW + timedelta(hours=7), timedelta(hours=6)) is True
    )
    await revocations.finish(TENANT, day, "done", NOW + timedelta(hours=7))
    assert (
        await revocations.claim(TENANT, day, NOW + timedelta(hours=20), timedelta(hours=6)) is False
    )
    assert await revocations.owed_since(TENANT) == NOW + timedelta(hours=7)


async def test_run_due_runs_each_tenant_once_and_finishes_it(
    archive, owner, verifications, revocations
):
    await _assigned(archive, owner, verifications)
    check = _check(revocations, ("alice", REVIEW))
    night = NOW.replace(hour=3)

    first = await run_due(check, revocations, [TENANT], night)
    second = await run_due(check, revocations, [TENANT], night + timedelta(minutes=15))

    assert first == {TENANT: "done"} and second == {}
    assert await owner.fetchval("SELECT outcome FROM revocation_runs") == "done"


async def test_a_revoke_never_takes_the_employees_own_self_made_wraps(archive, owner, revocations):
    """Key recovery makes the employee's wraps self-made; supervise is not their reason (§10.7)."""
    conversation, key_id, _ = await _ended(archive, owner, wrapped=False)
    await _granted(owner, key_id, "alice", "alice")
    deleted = await revocations.revoke(
        TENANT, conversation.conversation_id, [], ["alice"], "system", NOW
    )
    assert deleted == 0
    assert await owner.fetchval("SELECT count(*) FROM key_wraps WHERE recipient_ref = 'alice'") == 1
