"""The archive store's ports, names and failures (spec §12).

The gateway writes and reads ciphertext through `ArchiveWriter`. Only the
retention worker (#618) holds `ArchiveRetention`, whose credential may
extend locks, set legal holds and delete versions whose lock has lapsed.
No credential can delete a locked version: the storage enforces that.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol

from ...session_pseudonym import tenant_ref

BUCKET_PREFIX: Final[str] = "ssf-rec-"
# Spec §7: a message's up to three objects, and the other entry kinds' one each.
OBJECT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "original.wav",
        "translated.wav",
        "record.json",
        "consent.json",
        "playback.json",
        "amendment.json",
    }
)
_ID: Final[re.Pattern[str]] = re.compile(
    r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z"
)


class ArchiveError(Exception):
    """A storage request failed. `code` is the storage's error code or ours; never content."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ArchiveUnavailableError(ArchiveError):
    """The store could not be reached or answered 5xx: retry later."""


class ArchiveRefusedError(ArchiveError):
    """The store refused the request: a lock, a missing permission, a bad credential."""


class ArchiveNotFoundError(ArchiveError):
    """No such bucket, key or version."""


class ArchiveKeyExistsError(ArchiveError):
    """A put found the key already written (If-None-Match)."""


@dataclass(frozen=True)
class StoredVersion:
    version_id: str
    sha256: str  # hex of the bytes as stored, recorded when they were put


@dataclass(frozen=True)
class VersionRetention:
    mode: str | None
    retain_until: datetime | None
    legal_hold: bool


def bucket_for(tenant_id: str) -> str:
    """One bucket per tenant, named by the tenant reference so no identifier appears."""
    return BUCKET_PREFIX + tenant_ref(tenant_id)


def object_key(conversation_id: str, entry_id: str, object_type: str) -> str:
    """`<conversation_id>/<entry_id>/<object_type>`: UUIDs and a fixed type, no personal data."""
    if not _ID.fullmatch(conversation_id) or not _ID.fullmatch(entry_id):
        raise ValueError("conversation and entry IDs are lowercase UUIDs")
    if object_type not in OBJECT_TYPES:
        raise ValueError("unknown object type")
    return f"{conversation_id}/{entry_id}/{object_type}"


class ArchiveWriter(Protocol):
    async def put(self, tenant_id: str, key: str, data: bytes) -> StoredVersion:
        """Store `data` once under `key`. ArchiveKeyExistsError if the key was written before."""
        ...

    async def head(self, tenant_id: str, key: str) -> StoredVersion:
        """The key's current version, as put; used to recover after a lost put response."""
        ...

    async def get(self, tenant_id: str, key: str, version_id: str) -> bytes: ...


class ArchiveRetention(Protocol):
    async def retention(self, tenant_id: str, key: str, version_id: str) -> VersionRetention: ...

    async def extend_retention(
        self, tenant_id: str, key: str, version_id: str, until: datetime
    ) -> None: ...

    async def set_legal_hold(self, tenant_id: str, key: str, version_id: str, on: bool) -> None: ...

    async def delete_version(self, tenant_id: str, key: str, version_id: str) -> None:
        """Refused while the version is locked or held."""
        ...
