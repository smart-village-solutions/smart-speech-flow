"""The archive store on a local directory, for unit tests and local development (spec §12.2).

It keeps the S3 semantics the gateway relies on: every put makes a version,
a key is written once, every version is locked for the bucket's default
retention, retention only grows, and a locked or held version cannot be
deleted. It enforces them in code, which is no protection against whoever
can write the directory: production uses SeaweedFS.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .archive import (
    ArchiveKeyExistsError,
    ArchiveNotFoundError,
    ArchiveRefusedError,
    StoredVersion,
    VersionEntry,
    VersionRetention,
    bucket_for,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FilesystemArchiveStore:
    """ArchiveWriter and ArchiveRetention over `<root>/<bucket>/<key>/<version>.{bin,json}`."""

    def __init__(
        self,
        root: Path,
        default_retention: timedelta,
        *,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._root = root
        self._default_retention = default_retention
        self._clock = clock

    def _key_dir(self, tenant_id: str, key: str) -> Path:
        path = (self._root / bucket_for(tenant_id) / key).resolve()
        if not path.is_relative_to(self._root.resolve()):
            raise ArchiveRefusedError("key_outside_store")
        return path

    def _meta_path(self, tenant_id: str, key: str, version_id: str) -> Path:
        if not version_id.isalnum():
            raise ArchiveNotFoundError("NoSuchVersion")
        return self._key_dir(tenant_id, key) / f"{version_id}.json"

    def _read_meta(self, tenant_id: str, key: str, version_id: str) -> dict[str, object]:
        path = self._meta_path(tenant_id, key, version_id)
        try:
            return dict(json.loads(path.read_text()))
        except FileNotFoundError:
            raise ArchiveNotFoundError("NoSuchVersion") from None

    def _write_meta(
        self, tenant_id: str, key: str, version_id: str, meta: dict[str, object]
    ) -> None:
        path = self._meta_path(tenant_id, key, version_id)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(meta))
        os.replace(temporary, path)

    async def put(self, tenant_id: str, key: str, data: bytes) -> StoredVersion:
        directory = self._key_dir(tenant_id, key)
        directory.mkdir(parents=True, exist_ok=True)
        if any(directory.glob("*.json")):
            raise ArchiveKeyExistsError("PreconditionFailed")
        version_id = uuid.uuid4().hex
        digest = hashlib.sha256(data).hexdigest()
        (directory / f"{version_id}.bin").write_bytes(data)
        until = self._clock() + self._default_retention
        self._write_meta(
            tenant_id,
            key,
            version_id,
            {"sha256": digest, "retain_until": until.isoformat(), "legal_hold": False},
        )
        return StoredVersion(version_id, digest)

    async def head(self, tenant_id: str, key: str) -> StoredVersion:
        directory = self._key_dir(tenant_id, key)
        versions = sorted(directory.glob("*.json"), key=lambda path: path.stat().st_mtime_ns)
        if not versions:
            raise ArchiveNotFoundError("NoSuchKey")
        meta = json.loads(versions[-1].read_text())
        return StoredVersion(versions[-1].stem, str(meta["sha256"]))

    async def get(self, tenant_id: str, key: str, version_id: str) -> bytes:
        self._read_meta(tenant_id, key, version_id)
        return (self._key_dir(tenant_id, key) / f"{version_id}.bin").read_bytes()

    async def retention(self, tenant_id: str, key: str, version_id: str) -> VersionRetention:
        meta = self._read_meta(tenant_id, key, version_id)
        until = datetime.fromisoformat(str(meta["retain_until"]))
        return VersionRetention("COMPLIANCE", until, bool(meta["legal_hold"]))

    async def extend_retention(
        self, tenant_id: str, key: str, version_id: str, until: datetime
    ) -> None:
        meta = self._read_meta(tenant_id, key, version_id)
        if until < datetime.fromisoformat(str(meta["retain_until"])):
            raise ArchiveRefusedError("AccessDenied")
        self._write_meta(tenant_id, key, version_id, meta | {"retain_until": until.isoformat()})

    async def set_legal_hold(self, tenant_id: str, key: str, version_id: str, on: bool) -> None:
        meta = self._read_meta(tenant_id, key, version_id)
        self._write_meta(tenant_id, key, version_id, meta | {"legal_hold": on})

    async def delete_version(self, tenant_id: str, key: str, version_id: str) -> None:
        state = await self.retention(tenant_id, key, version_id)
        if state.legal_hold or (state.retain_until and state.retain_until > self._clock()):
            raise ArchiveRefusedError("AccessDenied")
        directory = self._key_dir(tenant_id, key)
        (directory / f"{version_id}.bin").unlink()
        self._meta_path(tenant_id, key, version_id).unlink()

    async def list_versions(self, tenant_id: str, prefix: str) -> list[VersionEntry]:
        bucket = self._root / bucket_for(tenant_id)
        # Each key is a directory of `<version>.json` files; keys themselves may end in .json.
        found = (
            VersionEntry(meta.parent.relative_to(bucket).as_posix(), meta.stem)
            for meta in bucket.rglob("*.json")
            if meta.is_file()
        )
        return sorted(entry for entry in found if entry.key.startswith(prefix))
