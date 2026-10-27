"""The archive store over the S3 protocol, as SeaweedFS serves it on the storage VM (spec §12).

Path-style requests to one endpoint, signed with SigV4 per call. The writer
credential of each tenant may put, head and get in that tenant's bucket; the
retention credential may change retention and delete lapsed versions; the
admin credential, used only by the provisioning commands, creates buckets.
"""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final, Protocol
from urllib.parse import quote, urlsplit

import aiohttp

from .archive import (
    ArchiveKeyExistsError,
    ArchiveNotFoundError,
    ArchiveRefusedError,
    ArchiveUnavailableError,
    StoredVersion,
    VersionRetention,
    bucket_for,
)
from .sigv4 import Credentials, payload_hash, sign

REGION: Final[str] = "us-east-1"
SHA256_META: Final[str] = "x-amz-meta-sha256"
_CODE = re.compile(rb"<Code>([A-Za-z0-9.]{1,64})</Code>")
_MODE = re.compile(rb"<Mode>(GOVERNANCE|COMPLIANCE)</Mode>")
_UNTIL = re.compile(rb"<RetainUntilDate>([0-9T:.\-+Z]{10,40})</RetainUntilDate>")
_HOLD = re.compile(rb"<Status>(ON|OFF)</Status>")
_DAYS = re.compile(rb"<Days>([0-9]{1,6})</Days>")
# What the store answers for a version that has no retention, or no legal hold, set.
_NOT_SET: Final[frozenset[str]] = frozenset(
    {"NoSuchObjectLockConfiguration", "NoSuchObjectRetention", "NoSuchObjectLegalHold"}
)


@dataclass(frozen=True)
class S3Response:
    status: int
    headers: Mapping[str, str]  # lower-case names
    body: bytes


class S3Transport(Protocol):
    async def send(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> S3Response: ...


class AiohttpS3Transport:
    """One connection pool for the store's lifetime."""

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    async def send(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> S3Response:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        # A redirect would resend the signed request to an address nobody configured.
        async with self._session.request(
            method,
            url,
            headers=dict(headers),
            data=body or None,
            timeout=timeout,
            allow_redirects=False,
        ) as response:
            return S3Response(
                response.status,
                {name.lower(): value for name, value in response.headers.items()},
                await response.read(),
            )

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()


_DEFAULT_PORTS: Final[dict[str, int]] = {"http": 80, "https": 443}


def _origin(endpoint: str) -> tuple[str, str]:
    """(scheme://host[:port], host[:port]) of an http(s) origin with no path or credentials."""
    parsed = urlsplit(endpoint)
    try:
        port = parsed.port
    except ValueError:
        raise ValueError("the archive endpoint has an invalid port") from None
    if port is not None and port == _DEFAULT_PORTS.get(parsed.scheme):
        # The client would send the Host header without it, and the signature would not match.
        raise ValueError("the archive endpoint must omit its scheme's default port")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("the archive endpoint must be an http(s) origin")
    if parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query:
        raise ValueError("the archive endpoint must be a bare origin")
    # The client sends the host in lower case, so it is signed that way too.
    host = parsed.netloc.lower()
    return f"{parsed.scheme}://{host}", host


def _code(response: S3Response) -> str:
    match = _CODE.search(response.body)
    return match.group(1).decode() if match else f"status_{response.status}"


def _raise_for(response: S3Response) -> None:
    status = response.status
    if status < 300:
        return
    code = _code(response)
    if status >= 500:
        raise ArchiveUnavailableError(code)
    if status == 404:
        raise ArchiveNotFoundError(code)
    if status == 412:
        raise ArchiveKeyExistsError(code)
    raise ArchiveRefusedError(code)


def _iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise ValueError("retention dates must be timezone-aware")
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _checksum(body: bytes) -> str:
    """The signed integrity header the store checks a body against; SHA-256 rather than MD5."""
    return base64.b64encode(hashlib.sha256(body).digest()).decode()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class S3Client:
    """Signs and sends one request; maps failures to the archive errors."""

    def __init__(
        self,
        endpoint: str,
        *,
        transport: S3Transport | None = None,
        timeout_seconds: float = 30.0,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._origin, self._host = _origin(endpoint)
        self._transport = transport or AiohttpS3Transport()
        self._timeout = timeout_seconds
        self._clock = clock

    async def request(
        self,
        credentials: Credentials,
        method: str,
        bucket: str,
        key: str = "",
        *,
        query: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        body: bytes = b"",
    ) -> S3Response:
        path = f"/{bucket}/{key}" if key else f"/{bucket}"
        query = dict(query or {})
        signed = sign(
            method=method,
            host=self._host,
            path=path,
            query=query,
            headers=dict(headers or {}),
            body_hash=payload_hash(body),
            credentials=credentials,
            region=REGION,
            now=self._clock(),
        )
        url = self._origin + quote(path, safe="/~")
        if query:
            url += "?" + "&".join(
                f"{quote(name, safe='~')}={quote(value, safe='~')}" for name, value in query.items()
            )
        try:
            response = await self._transport.send(method, url, signed, body, self._timeout)
        except (TimeoutError, aiohttp.ClientError):
            raise ArchiveUnavailableError("network_error") from None
        _raise_for(response)
        return response

    async def close(self) -> None:
        close = getattr(self._transport, "close", None)
        if close is not None:
            await close()


class S3ArchiveStore:
    """ArchiveWriter with each tenant's writer credential; ArchiveRetention with the retention one."""

    def __init__(self, client: S3Client, credentials_for: Callable[[str], Credentials]) -> None:
        self._client = client
        self._credentials_for = credentials_for

    async def _send(
        self,
        tenant_id: str,
        method: str,
        key: str,
        *,
        query: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        body: bytes = b"",
    ) -> S3Response:
        return await self._client.request(
            self._credentials_for(tenant_id),
            method,
            bucket_for(tenant_id),
            key,
            query=query,
            headers=headers,
            body=body,
        )

    async def put(self, tenant_id: str, key: str, data: bytes) -> StoredVersion:
        digest = hashlib.sha256(data).hexdigest()
        response = await self._send(
            tenant_id,
            "PUT",
            key,
            headers={
                "Content-Type": "application/octet-stream",
                "If-None-Match": "*",
                SHA256_META: digest,
                # The store refuses a body that does not match it (BadDigest).
                "x-amz-checksum-sha256": _checksum(data),
            },
            body=data,
        )
        version = response.headers.get("x-amz-version-id")
        if not version:
            # An unversioned bucket would let a later put replace this one.
            raise ArchiveRefusedError("unversioned_bucket")
        return StoredVersion(version, digest)

    async def head(self, tenant_id: str, key: str) -> StoredVersion:
        response = await self._send(tenant_id, "HEAD", key)
        version = response.headers.get("x-amz-version-id")
        if not version:
            raise ArchiveRefusedError("unversioned_bucket")
        return StoredVersion(version, response.headers.get(SHA256_META, ""))

    async def get(self, tenant_id: str, key: str, version_id: str) -> bytes:
        response = await self._send(tenant_id, "GET", key, query={"versionId": version_id})
        return response.body

    async def _lock_read(self, tenant_id: str, key: str, version_id: str, kind: str) -> bytes:
        """The body of a `?retention` or `?legal-hold` read; empty when none is set."""
        try:
            response = await self._send(
                tenant_id, "GET", key, query={kind: "", "versionId": version_id}
            )
        except ArchiveNotFoundError as error:
            if error.code not in _NOT_SET:
                raise
            return b""
        return response.body

    async def retention(self, tenant_id: str, key: str, version_id: str) -> VersionRetention:
        body = await self._lock_read(tenant_id, key, version_id, "retention")
        hold = _HOLD.search(await self._lock_read(tenant_id, key, version_id, "legal-hold"))
        mode, until = _MODE.search(body), _UNTIL.search(body)
        return VersionRetention(
            mode.group(1).decode() if mode else None,
            (
                datetime.fromisoformat(until.group(1).decode().replace("Z", "+00:00"))
                if until
                else None
            ),
            hold is not None and hold.group(1) == b"ON",
        )

    async def extend_retention(
        self, tenant_id: str, key: str, version_id: str, until: datetime
    ) -> None:
        body = (
            "<Retention><Mode>COMPLIANCE</Mode>"
            f"<RetainUntilDate>{_iso(until)}</RetainUntilDate></Retention>"
        ).encode()
        await self._send(
            tenant_id,
            "PUT",
            key,
            query={"retention": "", "versionId": version_id},
            headers={"x-amz-checksum-sha256": _checksum(body)},
            body=body,
        )

    async def set_legal_hold(self, tenant_id: str, key: str, version_id: str, on: bool) -> None:
        status = "ON" if on else "OFF"
        body = f"<LegalHold><Status>{status}</Status></LegalHold>".encode()
        await self._send(
            tenant_id,
            "PUT",
            key,
            query={"legal-hold": "", "versionId": version_id},
            headers={"x-amz-checksum-sha256": _checksum(body)},
            body=body,
        )

    async def delete_version(self, tenant_id: str, key: str, version_id: str) -> None:
        await self._send(tenant_id, "DELETE", key, query={"versionId": version_id})


class S3ArchiveAdmin:
    """Bucket provisioning with the storage admin credential, used only by the operator commands."""

    def __init__(self, client: S3Client, credentials: Credentials) -> None:
        self._client = client
        self._credentials = credentials

    async def create_bucket(self, tenant_id: str) -> str:
        """Creates the tenant's bucket with Object Lock; an existing one must already have it."""
        bucket = bucket_for(tenant_id)
        try:
            await self._client.request(
                self._credentials,
                "PUT",
                bucket,
                headers={"x-amz-bucket-object-lock-enabled": "true"},
            )
        except ArchiveRefusedError as error:
            if error.code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                raise
        # Object Lock can only be enabled at creation, so a bucket without it is useless here.
        try:
            lock = await self._client.request(
                self._credentials, "GET", bucket, query={"object-lock": ""}
            )
        except ArchiveNotFoundError:
            raise ArchiveRefusedError("bucket_without_object_lock") from None
        if b"<ObjectLockEnabled>Enabled</ObjectLockEnabled>" not in lock.body:
            raise ArchiveRefusedError("bucket_without_object_lock")
        return bucket

    async def set_default_retention(self, tenant_id: str, days: int) -> None:
        if not 1 <= days <= 36500:
            raise ValueError("the default retention is 1 to 36500 days")
        body = (
            "<ObjectLockConfiguration><ObjectLockEnabled>Enabled</ObjectLockEnabled>"
            f"<Rule><DefaultRetention><Mode>COMPLIANCE</Mode><Days>{days}</Days>"
            "</DefaultRetention></Rule></ObjectLockConfiguration>"
        ).encode()
        await self._client.request(
            self._credentials,
            "PUT",
            bucket_for(tenant_id),
            query={"object-lock": ""},
            headers={"x-amz-checksum-sha256": _checksum(body)},
            body=body,
        )

    async def default_retention_days(self, tenant_id: str) -> int | None:
        mode, days = await read_default_retention(self._client, self._credentials, tenant_id)
        return days if mode == "COMPLIANCE" else None


async def read_default_retention(
    client: S3Client, credentials: Credentials, tenant_id: str
) -> tuple[str | None, int | None]:
    """(mode, days) of the tenant bucket's default retention; (None, None) when it has none."""
    response = await client.request(
        credentials, "GET", bucket_for(tenant_id), query={"object-lock": ""}
    )
    mode, days = _MODE.search(response.body), _DAYS.search(response.body)
    return (
        mode.group(1).decode() if mode else None,
        int(days.group(1)) if days else None,
    )
