"""What the S3 adapter sends and how it reads the answers, without a store."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime, timezone

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from services.api_gateway.recording.storage.archive import (
    ArchiveKeyExistsError,
    ArchiveNotFoundError,
    ArchiveRefusedError,
    ArchiveUnavailableError,
    bucket_for,
    object_key,
)
from services.api_gateway.recording.storage.s3 import (
    AiohttpS3Transport,
    S3ArchiveAdmin,
    S3ArchiveStore,
    S3Client,
    S3Response,
)
from services.api_gateway.recording.storage.sigv4 import Credentials

ENDPOINT = "https" + "://archive.test:8333"
TENANT = "tenant-kassel"
KEY = object_key(
    "0d6c2b1a-9e8f-4d7c-b6a5-4f3e2d1c0b9a", "1e7d3c2b-0f9e-4e8d-a7b6-5a4f3e2d1c0b", "record.json"
)
WRITER = Credentials("writer-key", "writer-secret")


class RecordingTransport:
    def __init__(self, *responses: S3Response | Exception) -> None:
        self.responses = list(responses)
        self.sent: list[tuple[str, str, Mapping[str, str], bytes]] = []

    async def send(self, method, url, headers, body, timeout_seconds) -> S3Response:
        self.sent.append((method, url, headers, body))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _ok(headers: Mapping[str, str] | None = None, body: bytes = b"") -> S3Response:
    return S3Response(200, dict(headers or {}), body)


def _error(status: int, code: str) -> S3Response:
    return S3Response(status, {}, f"<Error><Code>{code}</Code></Error>".encode())


def _store(transport: RecordingTransport) -> S3ArchiveStore:
    client = S3Client(
        ENDPOINT, transport=transport, clock=lambda: datetime(2026, 10, 27, tzinfo=timezone.utc)
    )
    return S3ArchiveStore(client, lambda tenant: WRITER)


async def test_a_put_is_write_once_signed_and_carries_its_hash():
    transport = RecordingTransport(_ok({"x-amz-version-id": "v1"}))
    stored = await _store(transport).put(TENANT, KEY, b"ciphertext")

    method, url, headers, body = transport.sent[0]
    assert (method, body) == ("PUT", b"ciphertext")
    assert url == f"{ENDPOINT}/{bucket_for(TENANT)}/{KEY}"
    assert headers["if-none-match"] == "*"
    digest = hashlib.sha256(b"ciphertext").hexdigest()
    assert headers["x-amz-meta-sha256"] == digest == stored.sha256
    assert headers["x-amz-content-sha256"] == digest
    assert "if-none-match" in headers["Authorization"].split("SignedHeaders=")[1]
    assert "x-amz-object-lock-mode" not in headers  # the bucket default locks it
    assert stored.version_id == "v1"


async def test_a_put_into_an_unversioned_bucket_is_refused():
    with pytest.raises(ArchiveRefusedError) as refused:
        await _store(RecordingTransport(_ok())).put(TENANT, KEY, b"ciphertext")
    assert refused.value.code == "unversioned_bucket"


@pytest.mark.parametrize(
    ("response", "error", "code"),
    [
        (_error(412, "PreconditionFailed"), ArchiveKeyExistsError, "PreconditionFailed"),
        (_error(403, "AccessDenied"), ArchiveRefusedError, "AccessDenied"),
        (_error(404, "NoSuchVersion"), ArchiveNotFoundError, "NoSuchVersion"),
        (_error(503, "SlowDown"), ArchiveUnavailableError, "SlowDown"),
        (S3Response(502, {}, b"bad gateway"), ArchiveUnavailableError, "status_502"),
        (aiohttp.ClientConnectionError(), ArchiveUnavailableError, "network_error"),
        (TimeoutError(), ArchiveUnavailableError, "network_error"),
    ],
)
async def test_failures_map_to_archive_errors_by_code(response, error, code):
    with pytest.raises(error) as raised:
        await _store(RecordingTransport(response)).put(TENANT, KEY, b"ciphertext")
    assert raised.value.code == code


async def test_reads_name_the_version():
    transport = RecordingTransport(_ok(body=b"ciphertext"))
    assert await _store(transport).get(TENANT, KEY, "v1") == b"ciphertext"
    assert transport.sent[0][1].endswith(f"/{KEY}?versionId=v1")


async def test_a_head_returns_the_current_version_and_its_stored_hash():
    digest = hashlib.sha256(b"ciphertext").hexdigest()
    transport = RecordingTransport(
        _ok({"x-amz-version-id": "v7", "x-amz-meta-sha256": digest}), _ok()
    )
    store = _store(transport)
    stored = await store.head(TENANT, KEY)
    assert (stored.version_id, stored.sha256) == ("v7", digest)
    assert (transport.sent[0][0], transport.sent[0][1].endswith(f"/{KEY}")) == ("HEAD", True)
    with pytest.raises(ArchiveRefusedError) as refused:
        await store.head(TENANT, KEY)
    assert refused.value.code == "unversioned_bucket"


async def test_retention_reads_mode_date_and_hold_and_tolerates_none_set():
    retention = (
        b"<Retention><Mode>COMPLIANCE</Mode>"
        b"<RetainUntilDate>2026-11-01T00:00:00Z</RetainUntilDate></Retention>"
    )
    transport = RecordingTransport(_ok(body=retention), _error(404, "NoSuchObjectLegalHold"))
    state = await _store(transport).retention(TENANT, KEY, "v1")
    assert (state.mode, state.retain_until, state.legal_hold) == (
        "COMPLIANCE",
        datetime(2026, 11, 1, tzinfo=timezone.utc),
        False,
    )
    with pytest.raises(ArchiveNotFoundError):
        await _store(RecordingTransport(_error(404, "NoSuchVersion"))).retention(TENANT, KEY, "v9")


async def test_extending_sends_a_compliance_date_with_a_sha256_checksum():
    transport = RecordingTransport(_ok())
    until = datetime(2027, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    await _store(transport).extend_retention(TENANT, KEY, "v1", until)
    method, url, headers, body = transport.sent[0]
    assert method == "PUT" and "retention=" in url and "versionId=v1" in url
    assert b"<Mode>COMPLIANCE</Mode>" in body
    assert b"<RetainUntilDate>2027-01-02T03:04:05Z</RetainUntilDate>" in body
    assert "x-amz-checksum-sha256" in headers
    with pytest.raises(ValueError):
        await _store(RecordingTransport()).extend_retention(TENANT, KEY, "v1", datetime(2027, 1, 2))


async def test_a_legal_hold_and_a_version_delete_name_their_version():
    transport = RecordingTransport(_ok(), _ok())
    store = _store(transport)
    await store.set_legal_hold(TENANT, KEY, "v1", True)
    await store.delete_version(TENANT, KEY, "v1")
    assert b"<Status>ON</Status>" in transport.sent[0][3]
    assert (transport.sent[1][0], transport.sent[1][1].split("?")[1]) == ("DELETE", "versionId=v1")


async def test_a_bucket_is_created_with_object_lock_and_an_existing_one_must_have_it():
    enabled = _ok(body=b"<ObjectLockEnabled>Enabled</ObjectLockEnabled>")
    transport = RecordingTransport(_ok(), enabled, _error(409, "BucketAlreadyOwnedByYou"), enabled)
    admin = S3ArchiveAdmin(S3Client(ENDPOINT, transport=transport), Credentials("a", "b"))
    assert await admin.create_bucket(TENANT) == bucket_for(TENANT)
    assert transport.sent[0][2]["x-amz-bucket-object-lock-enabled"] == "true"
    assert await admin.create_bucket(TENANT) == bucket_for(TENANT)

    for lock_answer in (
        _error(404, "ObjectLockConfigurationNotFoundError"),
        _ok(body=b"<ObjectLockConfiguration></ObjectLockConfiguration>"),
    ):
        unlocked = RecordingTransport(_error(409, "BucketAlreadyOwnedByYou"), lock_answer)
        admin = S3ArchiveAdmin(S3Client(ENDPOINT, transport=unlocked), Credentials("a", "b"))
        with pytest.raises(ArchiveRefusedError) as refused:
            await admin.create_bucket(TENANT)
        assert refused.value.code == "bucket_without_object_lock"


async def test_the_default_retention_is_compliance_in_days():
    transport = RecordingTransport(
        _ok(),
        _ok(body=b"<Mode>COMPLIANCE</Mode><Days>31</Days>"),
        _ok(body=b"<Mode>GOVERNANCE</Mode><Days>31</Days>"),
    )
    admin = S3ArchiveAdmin(S3Client(ENDPOINT, transport=transport), Credentials("a", "b"))
    await admin.set_default_retention(TENANT, 31)
    assert b"<Mode>COMPLIANCE</Mode><Days>31</Days>" in transport.sent[0][3]
    assert await admin.default_retention_days(TENANT) == 31
    assert await admin.default_retention_days(TENANT) is None  # governance can be bypassed
    with pytest.raises(ValueError):
        await admin.set_default_retention(TENANT, 0)


@pytest.mark.parametrize(
    "endpoint",
    [
        "ftp" + "://archive.test",
        "https" + "://user:pw@archive.test",
        "https" + "://archive.test/x",
        "https" + "://archive.test:443",
        "http" + "://archive.test:80",
        "archive",
    ],
)
def test_the_endpoint_is_a_bare_http_origin(endpoint):
    with pytest.raises(ValueError):
        S3Client(endpoint)


async def test_the_transport_never_follows_a_redirect():
    async def elsewhere(request: web.Request) -> web.Response:
        raise web.HTTPTemporaryRedirect("/elsewhere")

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", elsewhere)
    async with TestServer(app) as server:
        client = S3Client(str(server.make_url("")).rstrip("/"), transport=AiohttpS3Transport())
        try:
            with pytest.raises(ArchiveRefusedError) as refused:
                await client.request(WRITER, "PUT", bucket_for(TENANT), KEY, body=b"ciphertext")
        finally:
            await client.close()
    assert refused.value.code == "status_307"
