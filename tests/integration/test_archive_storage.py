"""The archive store's guarantees, against a real SeaweedFS primary and replica (#613).

scripts/recording/archive-test-stack.sh up "$PWD/.archive-test"
set -a; . .archive-test/archive-test.env; set +a
pytest --run-integration tests/integration/test_archive_storage.py
scripts/recording/archive-test-stack.sh down

With SSF_ARCHIVE_TEST_REQUIRED set, as in CI, a missing store fails the run
instead of skipping it.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from services.api_gateway.recording.storage import admin as archive_admin
from services.api_gateway.recording.storage.archive import (
    ArchiveKeyExistsError,
    ArchiveRefusedError,
    bucket_for,
    object_key,
)
from services.api_gateway.recording.storage.s3 import (
    S3ArchiveAdmin,
    S3ArchiveStore,
    S3Client,
    read_default_retention,
)
from services.api_gateway.recording.storage.settings import ArchiveSettings
from services.api_gateway.recording.storage.sigv4 import Credentials
from services.api_gateway.recording.storage.spool import ArchiveSpool, ArchiveUploader

pytestmark = pytest.mark.integration

ENDPOINT = os.environ.get("SSF_ARCHIVE_TEST_ENDPOINT", "")
REPLICA_ENDPOINT = os.environ.get("SSF_ARCHIVE_TEST_REPLICA_ENDPOINT", "")
TENANT = os.environ.get("SSF_ARCHIVE_TEST_TENANT", "tenant-ci")
REPLICA_WAIT_SECONDS = 30


def _credentials(variable: str) -> Credentials:
    key, _, secret = os.environ.get(variable, "").partition(":")
    return Credentials(key, secret)


def _key(object_type: str = "record.json") -> str:
    return object_key(str(uuid.uuid4()), str(uuid.uuid4()), object_type)


def _absent(variable: str) -> None:
    if os.environ.get("SSF_ARCHIVE_TEST_REQUIRED"):
        pytest.fail(f"{variable} is not set")
    pytest.skip(f"{variable} is not set")


@pytest.fixture
async def stores():
    if not ENDPOINT:
        _absent("SSF_ARCHIVE_TEST_ENDPOINT")
    client = S3Client(ENDPOINT)
    admin = S3ArchiveAdmin(client, _credentials("SSF_ARCHIVE_TEST_ADMIN"))
    await admin.create_bucket(TENANT)
    await admin.set_default_retention(TENANT, 2)
    yield {
        "client": client,
        "admin": admin,
        "writer": S3ArchiveStore(client, lambda _: _credentials("SSF_ARCHIVE_TEST_WRITER")),
        "retention": S3ArchiveStore(client, lambda _: _credentials("SSF_ARCHIVE_TEST_RETENTION")),
        "root": S3ArchiveStore(client, lambda _: _credentials("SSF_ARCHIVE_TEST_ADMIN")),
    }
    await client.close()


async def test_a_locked_version_cannot_be_deleted_with_any_credential(stores):
    key = _key()
    stored = await stores["writer"].put(TENANT, key, b"ciphertext")
    for name in ("writer", "retention", "root"):
        with pytest.raises(ArchiveRefusedError):
            await stores[name].delete_version(TENANT, key, stored.version_id)
    # Not even with the governance bypass, which compliance mode ignores.
    with pytest.raises(ArchiveRefusedError):
        await stores["client"].request(
            _credentials("SSF_ARCHIVE_TEST_ADMIN"),
            "DELETE",
            bucket_for(TENANT),
            key,
            query={"versionId": stored.version_id},
            headers={"x-amz-bypass-governance-retention": "true"},
        )
    assert await stores["writer"].get(TENANT, key, stored.version_id) == b"ciphertext"


async def test_an_overwrite_and_a_delete_marker_leave_the_original_readable(stores):
    key = _key()
    stored = await stores["writer"].put(TENANT, key, b"original")
    with pytest.raises(ArchiveKeyExistsError):
        await stores["writer"].put(TENANT, key, b"replacement")
    admin, bucket = _credentials("SSF_ARCHIVE_TEST_ADMIN"), bucket_for(TENANT)
    client = stores["client"]
    # The admin may overwrite (no If-None-Match) and delete without a version.
    await client.request(admin, "PUT", bucket, key, body=b"replacement")
    marker = await client.request(admin, "DELETE", bucket, key)
    assert marker.headers.get("x-amz-delete-marker") == "true"
    assert await stores["writer"].get(TENANT, key, stored.version_id) == b"original"


async def test_retention_extends_and_never_shortens(stores):
    key = _key()
    stored = await stores["writer"].put(TENANT, key, b"ciphertext")
    locked = await stores["retention"].retention(TENANT, key, stored.version_id)
    assert locked.mode == "COMPLIANCE"
    later = locked.retain_until + timedelta(days=30)
    await stores["retention"].extend_retention(TENANT, key, stored.version_id, later)
    assert (
        await stores["retention"].retention(TENANT, key, stored.version_id)
    ).retain_until == later
    for name in ("retention", "root"):
        with pytest.raises(ArchiveRefusedError):
            await stores[name].extend_retention(TENANT, key, stored.version_id, locked.retain_until)
    with pytest.raises(ArchiveRefusedError):
        await stores["writer"].extend_retention(TENANT, key, stored.version_id, later)


async def test_a_lapsed_version_is_deleted_only_without_a_legal_hold(stores):
    held, free = _key(), _key()
    soon = datetime.now(timezone.utc) + timedelta(seconds=3)
    versions = {}
    admin, bucket = _credentials("SSF_ARCHIVE_TEST_ADMIN"), bucket_for(TENANT)
    for key in (held, free):
        response = await stores["client"].request(
            admin,
            "PUT",
            bucket,
            key,
            headers={
                "x-amz-object-lock-mode": "COMPLIANCE",
                "x-amz-object-lock-retain-until-date": soon.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            body=b"short-lived",
        )
        versions[key] = response.headers["x-amz-version-id"]
    await stores["retention"].set_legal_hold(TENANT, held, versions[held], True)
    await asyncio.sleep(5)
    with pytest.raises(ArchiveRefusedError):
        await stores["retention"].delete_version(TENANT, held, versions[held])
    await stores["retention"].delete_version(TENANT, free, versions[free])


async def test_a_writer_reaches_no_other_tenant(stores):
    other = "tenant-other"
    await stores["admin"].create_bucket(other)
    key = _key()
    stored = await stores["root"].put(other, key, b"other tenant")
    with pytest.raises(ArchiveRefusedError):
        await stores["writer"].put(other, _key(), b"ciphertext")
    with pytest.raises(ArchiveRefusedError):
        await stores["writer"].get(other, key, stored.version_id)


def _xml(root: str, inner: str) -> bytes:
    return f"<{root}>{inner}</{root}>".encode()


BUCKET_CHANGES = {
    "lower the default retention": (
        "PUT",
        "object-lock",
        _xml(
            "ObjectLockConfiguration",
            "<ObjectLockEnabled>Enabled</ObjectLockEnabled><Rule><DefaultRetention>"
            "<Mode>GOVERNANCE</Mode><Days>1</Days></DefaultRetention></Rule>",
        ),
    ),
    "drop the default retention": (
        "PUT",
        "object-lock",
        _xml("ObjectLockConfiguration", "<ObjectLockEnabled>Enabled</ObjectLockEnabled>"),
    ),
    "add an expiry rule": (
        "PUT",
        "lifecycle",
        _xml(
            "LifecycleConfiguration",
            "<Rule><ID>x</ID><Filter><Prefix></Prefix></Filter><Status>Enabled</Status>"
            "<Expiration><Days>1</Days></Expiration></Rule>",
        ),
    ),
    "suspend versioning": (
        "PUT",
        "versioning",
        _xml("VersioningConfiguration", "<Status>Suspended</Status>"),
    ),
    "set a bucket policy": (
        "PUT",
        "policy",
        b'{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":"*",'
        b'"Action":"s3:*","Resource":"*"}]}',
    ),
    "set CORS": (
        "PUT",
        "cors",
        _xml(
            "CORSConfiguration",
            "<CORSRule><AllowedOrigin>*</AllowedOrigin><AllowedMethod>GET</AllowedMethod></CORSRule>",
        ),
    ),
    "delete the bucket": ("DELETE", "", b""),
}


@pytest.mark.parametrize("change", sorted(BUCKET_CHANGES))
@pytest.mark.parametrize("credential", ["SSF_ARCHIVE_TEST_WRITER", "SSF_ARCHIVE_TEST_RETENTION"])
async def test_no_application_credential_changes_the_bucket(stores, credential, change):
    method, subresource, body = BUCKET_CHANGES[change]
    headers = {"Content-MD5": base64.b64encode(hashlib.md5(body).digest()).decode()} if body else {}
    with pytest.raises(ArchiveRefusedError):
        await stores["client"].request(
            _credentials(credential),
            method,
            bucket_for(TENANT),
            query={subresource: ""} if subresource else None,
            headers=headers,
            body=body,
        )
    admin = _credentials("SSF_ARCHIVE_TEST_ADMIN")
    assert await read_default_retention(stores["client"], admin, TENANT) == ("COMPLIANCE", 2)


async def test_the_check_command_passes_for_an_onboarded_tenant(stores):
    settings = ArchiveSettings(ENDPOINT, {TENANT: _credentials("SSF_ARCHIVE_TEST_WRITER")})
    assert await archive_admin.check(settings) == [f"ok    {TENANT} {bucket_for(TENANT)} 2 days"]


async def test_creating_a_bucket_twice_is_fine_but_a_bucket_without_lock_is_refused(stores):
    assert await stores["admin"].create_bucket(TENANT) == bucket_for(TENANT)
    plain = f"tenant-unlocked-{uuid.uuid4().hex[:8]}"
    await stores["client"].request(_credentials("SSF_ARCHIVE_TEST_ADMIN"), "PUT", bucket_for(plain))
    with pytest.raises(ArchiveRefusedError) as refused:
        await stores["admin"].create_bucket(plain)
    assert refused.value.code == "bucket_without_object_lock"


async def test_the_spool_flushes_in_order_after_an_outage(stores, tmp_path: Path):
    spool = ArchiveSpool(tmp_path / "spool")
    keys = [_key() for _ in range(3)]
    for number, key in enumerate(keys):
        spool.submit(TENANT, key, f"ciphertext-{number}".encode())
    recorded: list[tuple[int, str]] = []

    async def on_stored(item, stored):
        recorded.append((item.seq, stored.version_id))

    unreachable_client = S3Client("http://" + "127.0.0.1:1")
    unreachable = S3ArchiveStore(
        unreachable_client, lambda _: _credentials("SSF_ARCHIVE_TEST_WRITER")
    )
    try:
        assert await ArchiveUploader(spool, unreachable, on_stored).flush() is False
    finally:
        await unreachable_client.close()
    assert (spool.pending, recorded) == (3, [])

    assert await ArchiveUploader(spool, stores["writer"], on_stored).flush() is True
    assert [seq for seq, _ in recorded] == [1, 2, 3]
    for number, (key, (_, version)) in enumerate(zip(keys, recorded)):
        assert await stores["writer"].get(TENANT, key, version) == f"ciphertext-{number}".encode()


async def test_a_lost_answer_is_recovered_from_the_stored_version(stores, tmp_path: Path):
    key = _key()
    stored = await stores["writer"].put(TENANT, key, b"ciphertext")
    recorded = []

    async def on_stored(item, version):
        recorded.append(version)

    spool = ArchiveSpool(tmp_path / "spool")
    spool.submit(TENANT, key, b"ciphertext")  # as if the first put's answer never arrived
    assert await ArchiveUploader(spool, stores["writer"], on_stored).flush() is True
    assert recorded == [stored]

    other = ArchiveSpool(tmp_path / "other")
    other.submit(TENANT, key, b"other bytes")
    assert await ArchiveUploader(other, stores["writer"], on_stored).flush() is False
    assert (other.pending, recorded) == (1, [stored])


async def _replica_copy(replica: S3ArchiveStore, key: str, version_id: str) -> bytes:
    for _ in range(REPLICA_WAIT_SECONDS):
        try:
            return await replica.get(TENANT, key, version_id)
        except Exception:
            await asyncio.sleep(1)
    raise AssertionError("the version never reached the replica")


async def test_the_replica_keeps_locked_copies_that_survive_deletion_on_the_primary(stores):
    if not REPLICA_ENDPOINT:
        _absent("SSF_ARCHIVE_TEST_REPLICA_ENDPOINT")
    replica_client = S3Client(REPLICA_ENDPOINT)
    replica = S3ArchiveStore(
        replica_client, lambda _: _credentials("SSF_ARCHIVE_TEST_REPLICA_ADMIN")
    )
    try:
        key = _key("original.wav")
        stored = await stores["writer"].put(TENANT, key, b"x" * 200_000)
        assert await _replica_copy(replica, key, stored.version_id) == b"x" * 200_000
        copy = await replica.retention(TENANT, key, stored.version_id)
        assert copy.mode == "COMPLIANCE" and copy.retain_until is not None
        with pytest.raises(ArchiveRefusedError):
            await replica.delete_version(TENANT, key, stored.version_id)

        # A version deleted on the primary once its lock lapsed stays on the replica.
        lapsing = _key()
        soon = datetime.now(timezone.utc) + timedelta(seconds=3)
        response = await stores["client"].request(
            _credentials("SSF_ARCHIVE_TEST_ADMIN"),
            "PUT",
            bucket_for(TENANT),
            lapsing,
            headers={
                "x-amz-object-lock-mode": "COMPLIANCE",
                "x-amz-object-lock-retain-until-date": soon.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            body=b"lapsing",
        )
        version = response.headers["x-amz-version-id"]
        assert await _replica_copy(replica, lapsing, version) == b"lapsing"
        await asyncio.sleep(4)
        await stores["retention"].delete_version(TENANT, lapsing, version)
        await asyncio.sleep(5)
        assert await replica.get(TENANT, lapsing, version) == b"lapsing"
    finally:
        await replica_client.close()
