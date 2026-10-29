"""Both sites' retention workers against a real SeaweedFS pair and PostgreSQL (#618).

scripts/recording/archive-test-stack.sh up "$PWD/.archive-test"
GITHUB_ENV=.archive-test/postgres.env scripts/ci/start-recording-postgres.sh
set -a; . .archive-test/archive-test.env; . .archive-test/postgres.env; set +a
pytest --run-integration tests/integration/test_retention_two_sites.py

Never against the production store: an extension locks test versions for weeks.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from services.api_gateway.recording.repository import PostgresRecordingRepository
from services.api_gateway.recording.retention.decisions import RetentionDecision
from services.api_gateway.recording.retention.decisions_repository import (
    PostgresRetentionDecisions,
)
from services.api_gateway.recording.retention.restore_guard import AuditHighWater
from services.api_gateway.recording.retention.settings import WorkerSettings
from services.api_gateway.recording.retention.store import PostgresRetentionStore
from services.api_gateway.recording.retention.worker import RetentionWorker
from services.api_gateway.recording.storage.archive import (
    ArchiveRefusedError,
    bucket_for,
    object_key,
)
from services.api_gateway.recording.storage.s3 import S3ArchiveAdmin, S3ArchiveStore, S3Client
from tests.integration import test_archive_storage as storage_tests
from tests.integration import test_recording_archive_database as archive_database

pytestmark = pytest.mark.integration

owner = archive_database.owner
archive = archive_database.archive
_credentials = storage_tests._credentials
_replica_copy = storage_tests._replica_copy
TENANT = storage_tests.TENANT
SITES = {
    "primary": (
        "SSF_ARCHIVE_TEST_ENDPOINT",
        "SSF_ARCHIVE_TEST_RETENTION",
        "SSF_RECORDING_RETENTION_DATABASE",
    ),
    "replica": (
        "SSF_ARCHIVE_TEST_REPLICA_ENDPOINT",
        "SSF_ARCHIVE_TEST_REPLICA_RETENTION",
        "SSF_RECORDING_REPLICA_DATABASE",
    ),
}


def _settings(site: str, state_dir, endpoint: str | None = None) -> WorkerSettings:
    endpoint_variable, pair, database = SITES[site]
    for variable in (endpoint_variable, pair, f"{database}_URL"):
        if not os.environ.get(variable):
            storage_tests._absent(variable)
    return WorkerSettings(
        site=site,  # type: ignore[arg-type]
        endpoint=endpoint or os.environ[endpoint_variable],
        credentials=_credentials(pair),
        database_url=os.environ[f"{database}_URL"],
        database_password=os.environ.get(f"{database}_PASSWORD", ""),
        state_dir=state_dir / site,
    )


class Site:
    """One site's worker and the S3 view its retention pair gives."""

    def __init__(self, settings: WorkerSettings) -> None:
        self.settings = settings
        self.client = S3Client(settings.endpoint)
        self.archive = S3ArchiveStore(self.client, lambda _: settings.credentials)

    async def run(self):
        store = await PostgresRetentionStore.connect(self.settings)
        try:
            worker = RetentionWorker(
                self.settings, store, self.archive, AuditHighWater(self.settings.state_dir)
            )
            return await worker.run_once()
        finally:
            await store.close()

    async def lock(self, key: str, version_id: str):
        return await self.archive.retention(TENANT, key, version_id)

    async def listed(self, conversation_id: str):
        return await self.archive.list_versions(TENANT, f"{conversation_id}/")


@pytest.fixture
async def sites(archive, tmp_path):
    opened = {site: Site(_settings(site, tmp_path)) for site in SITES}
    admin = S3ArchiveAdmin(opened["primary"].client, _credentials("SSF_ARCHIVE_TEST_ADMIN"))
    await admin.create_bucket(TENANT)
    await admin.set_default_retention(TENANT, 2)
    yield opened
    for site in opened.values():
        await site.client.close()


@pytest.fixture
async def gateway(archive):
    base = await PostgresRecordingRepository.create(
        dsn=archive_database.APP_DSN, password=archive_database.APP_PASSWORD
    )
    yield PostgresRetentionDecisions(base.pool)
    await base.close()


async def _recorded(archive, sites, *, lock_seconds: int | None = None):
    """A conversation as the gateway opens it, its consent object stored and copied."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    record = dataclasses.replace(
        archive_database._conversation(TENANT),
        started_at=now - timedelta(hours=1),
        retention_until=now + timedelta(days=30),
    )
    conversation, _, _, consent = await archive_database._opened(archive, record)
    key = object_key(conversation.conversation_id, consent.entry_id, "record.json")
    primary = sites["primary"]
    headers = {}
    if lock_seconds is not None:
        until = datetime.now(timezone.utc) + timedelta(seconds=lock_seconds)
        headers = {
            "x-amz-object-lock-mode": "COMPLIANCE",
            "x-amz-object-lock-retain-until-date": until.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    response = await primary.client.request(
        _credentials("SSF_ARCHIVE_TEST_ADMIN"),
        "PUT",
        bucket_for(TENANT),
        key,
        headers=headers,
        body=b"ciphertext",
    )
    version = response.headers["x-amz-version-id"]
    await archive.record_stored(TENANT, consent.entry_id, "record.json", version, now)
    replica_admin = S3ArchiveStore(
        sites["replica"].client, lambda _: _credentials("SSF_ARCHIVE_TEST_REPLICA_ADMIN")
    )
    assert await _replica_copy(replica_admin, key, version) == b"ciphertext"
    return conversation, key, version


def _decision(conversation, kind, until=None) -> RetentionDecision:
    return RetentionDecision(
        tenant_id=TENANT,
        decision_id=str(uuid.uuid4()),
        conversation_id=conversation.conversation_id,
        at=datetime.now(timezone.utc),
        actor_sub="supervisor",
        kind=kind,
        retain_until=until,
        reason="two-site test",
    )


async def _expire_by_owner(owner, conversation) -> None:
    await owner.execute(
        "UPDATE conversations SET retention_until = now() - interval '1 minute',"
        " ended_at = now() - interval '2 minutes' WHERE conversation_id = $1",
        uuid.UUID(conversation.conversation_id),
    )


async def test_an_extension_reaches_both_sites(archive, sites, gateway):
    conversation, key, version = await _recorded(archive, sites)
    until = conversation.retention_until + timedelta(days=30)
    await gateway.decide(_decision(conversation, "extend", until), "recording.retention.extended")

    for site in sites.values():
        report = await site.run()
        assert report.failures == 0, report

    for name, site in sites.items():
        assert (await site.lock(key, version)).retain_until == until, name


async def test_shortening_is_refused_on_both_sites(archive, sites):
    _, key, version = await _recorded(archive, sites)
    for name, site in sites.items():
        current = (await site.lock(key, version)).retain_until
        with pytest.raises(ArchiveRefusedError):
            await site.archive.extend_retention(TENANT, key, version, current - timedelta(hours=1))
        assert (await site.lock(key, version)).retain_until == current, name


async def test_a_legal_hold_reaches_both_sites_and_blocks_expiry(archive, owner, sites, gateway):
    conversation, key, version = await _recorded(archive, sites)
    await gateway.decide(_decision(conversation, "hold_on"), "recording.legal_hold.on")
    await _expire_by_owner(owner, conversation)

    for site in sites.values():
        assert (await site.run()).failures == 0

    assert (
        await owner.fetchval(
            "SELECT shredded_at FROM conversations WHERE conversation_id = $1",
            uuid.UUID(conversation.conversation_id),
        )
        is None
    )
    for name, site in sites.items():
        assert (await site.lock(key, version)).legal_hold is True, name

    # Lifted again, so nothing stays held in the store after the test.
    await gateway.decide(_decision(conversation, "hold_off"), "recording.legal_hold.off")
    for site in sites.values():
        await site.run()
    for name, site in sites.items():
        assert (await site.lock(key, version)).legal_hold is False, name


async def test_expiry_shreds_before_deleting_then_clears_both_sites(archive, owner, sites):
    conversation, key, version = await _recorded(archive, sites, lock_seconds=8)
    conversation_id = uuid.UUID(conversation.conversation_id)
    await _expire_by_owner(owner, conversation)

    first = await sites["primary"].run()

    assert first.shredded == 1
    wraps = await owner.fetchval(
        "SELECT count(*) FROM key_wraps w JOIN conversation_keys k USING (tenant_id, key_id)"
        " WHERE k.conversation_id = $1",
        conversation_id,
    )
    assert wraps == 0
    for name, site in sites.items():
        assert [entry.version_id for entry in await site.listed(conversation.conversation_id)] == [
            version
        ], name

    await asyncio.sleep(10)
    for _ in range(2):
        for site in sites.values():
            await site.run()

    for name, site in sites.items():
        assert await site.listed(conversation.conversation_id) == [], name
    assert (
        await owner.fetchval(
            "SELECT count(*) FROM conversations WHERE conversation_id = $1", conversation_id
        )
        == 0
    )
    events = [
        row["event_type"]
        for row in await owner.fetch(
            "SELECT event_type FROM audit_events WHERE tenant_id = $1 AND object_ref = $2"
            " ORDER BY seq",
            TENANT,
            conversation.conversation_id,
        )
    ]
    assert events == ["recording.shredded", "recording.versions_deleted", "recording.expired"]


async def test_a_failing_site_is_retried_not_skipped(archive, owner, sites, tmp_path):
    await _recorded(archive, sites)
    unreachable = Site(_settings("replica", tmp_path, endpoint="http://" + "127.0.0.1:1"))
    try:
        report = await unreachable.run()
    finally:
        await unreachable.client.close()
    assert report.failures >= 1
    failing = await owner.fetchrow(
        "SELECT attempts, failing_since FROM version_locks WHERE site = 'replica'"
    )
    assert failing["attempts"] == 1 and failing["failing_since"] is not None

    await owner.execute("UPDATE version_locks SET next_attempt_at = now() WHERE site = 'replica'")
    assert (await sites["replica"].run()).failures == 0

    recovered = await owner.fetchrow(
        "SELECT attempts, failing_since, checked_at FROM version_locks WHERE site = 'replica'"
    )
    assert (recovered["attempts"], recovered["failing_since"]) == (0, None)
    assert recovered["checked_at"] is not None
