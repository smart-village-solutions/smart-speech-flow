"""An employee's own archive (spec §10.6).

The gateway serves what the browser needs to check and decrypt, and nothing
it could read itself. An open is the audited act; object fetches ride on an
open by the same caller in the last hour, remembered in memory, so a client
cannot keep fetching for the rest of the retention without a new audit event.
An amendment is sealed and committed like any entry, then spooled.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Final, Protocol

from ..clock import utc_now
from .archive_access_repository import (
    ArchiveAccessRefusedError,
    ExistingAmendment,
    ObjectLocation,
    OpenedConversation,
    OwnConversation,
)
from .chain import ChainEntry, ChainObject, objects_json, seal_entry
from .repository import RecordingStorageUnavailable
from .secrets import RecordingSecrets
from .storage.archive import ArchiveError, ArchiveNotFoundError, ArchiveWriter, object_key
from .storage.spool import SpoolFullError
from .storage.tenant_spools import TenantSpools

logger = logging.getLogger(__name__)

RECENT_OPEN: Final[timedelta] = timedelta(hours=1)
MAX_AMENDMENT_BYTES: Final[int] = 32 * 1024
REPORT_INTERVAL: Final[timedelta] = timedelta(minutes=10)
INTEGRITY_STAGES: Final[frozenset[str]] = frozenset({"trust", "wrap", "chain", "stamp", "object"})
AMENDMENT: Final[str] = "amendment.json"
# Version byte, nonce and tag: the smallest envelope A.3 can produce.
_ENVELOPE_MIN: Final[int] = 1 + 12 + 16


class ArchiveAccessError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class AccessRepository(Protocol):
    async def own_conversations(
        self,
        tenant_id: str,
        sub: str,
        now: datetime,
        *,
        limit: int,
        started_before: datetime | None,
        before_id: str | None,
    ) -> list[OwnConversation]: ...

    async def open(
        self, tenant_id: str, sub: str, conversation_id: str, now: datetime
    ) -> OpenedConversation | None: ...

    async def openable(
        self, tenant_id: str, sub: str, conversation_id: str, now: datetime
    ) -> bool: ...

    async def object_location(
        self,
        tenant_id: str,
        sub: str,
        conversation_id: str,
        entry_id: str,
        object_type: str,
        now: datetime,
    ) -> ObjectLocation | None: ...

    async def existing_amendment(
        self, tenant_id: str, sub: str, conversation_id: str, entry_id: str, now: datetime
    ) -> ExistingAmendment | None: ...

    async def append_amendment(
        self,
        tenant_id: str,
        sub: str,
        conversation_id: str,
        key_id: str,
        now: datetime,
        seal: Callable[[int, bytes], ChainEntry],
        audit_at: datetime,
    ) -> ChainEntry: ...

    async def record_not_found(
        self, tenant_id: str, sub: str, conversation_ref: str, at: datetime
    ) -> None: ...

    async def record_integrity_failure(
        self, tenant_id: str, sub: str, conversation_id: str, stage: str, at: datetime
    ) -> None: ...

    async def mark_incomplete(self, tenant_id: str, conversation_id: str) -> None: ...


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def _guard[T](work: Awaitable[T]) -> T:
    try:
        return await work
    except RecordingStorageUnavailable:
        raise ArchiveAccessError("unavailable") from None


class ArchiveAccess:
    def __init__(
        self,
        *,
        repository: AccessRepository,
        reader: ArchiveWriter,
        spools: TenantSpools,
        secrets: RecordingSecrets,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository = repository
        self._reader = reader
        self._spools = spools
        self._secrets = secrets
        self._clock = clock
        self._opened: dict[tuple[str, str, str], datetime] = {}
        self._reported: dict[tuple[str, str, str, str], datetime] = {}

    async def conversations(
        self,
        tenant_id: str,
        sub: str,
        *,
        limit: int,
        started_before: datetime | None,
        before_id: str | None,
    ) -> list[OwnConversation]:
        return await _guard(
            self._repository.own_conversations(
                tenant_id,
                sub,
                self._clock(),
                limit=limit,
                started_before=started_before,
                before_id=before_id,
            )
        )

    async def open(self, tenant_id: str, sub: str, conversation_id: str) -> OpenedConversation:
        now = self._clock()
        opened = await _guard(self._repository.open(tenant_id, sub, conversation_id, now))
        if opened is None:
            raise ArchiveAccessError("not_found")
        self._prune(now)
        self._opened[(tenant_id, sub, conversation_id)] = now
        return opened

    async def _not_found(
        self, tenant_id: str, sub: str, conversation_ref: str
    ) -> ArchiveAccessError:
        """Spec §17: every refusal is a 404 and an audit event, whichever route it came by."""
        await _guard(
            self._repository.record_not_found(tenant_id, sub, conversation_ref, self._clock())
        )
        return ArchiveAccessError("not_found")

    def _recently_opened(self, tenant_id: str, sub: str, conversation_id: str) -> bool:
        at = self._opened.get((tenant_id, sub, conversation_id))
        return at is not None and self._clock() - at <= RECENT_OPEN

    def _prune(self, now: datetime) -> None:
        self._opened = {
            marker: at for marker, at in self._opened.items() if now - at <= RECENT_OPEN
        }

    async def object(
        self, tenant_id: str, sub: str, conversation_id: str, entry_id: str, object_type: str
    ) -> bytes:
        if not self._recently_opened(tenant_id, sub, conversation_id):
            raise await self._not_found(tenant_id, sub, conversation_id)
        location = await _guard(
            self._repository.object_location(
                tenant_id, sub, conversation_id, entry_id, object_type, self._clock()
            )
        )
        if location is None:
            raise await self._not_found(tenant_id, sub, conversation_id)
        if location.version_id is None:
            raise ArchiveAccessError("not_stored")
        try:
            return await self._reader.get(tenant_id, location.key, location.version_id)
        except ArchiveNotFoundError:
            raise ArchiveAccessError("not_stored") from None
        except ArchiveError:
            raise ArchiveAccessError("unavailable") from None

    async def amend(
        self,
        tenant_id: str,
        sub: str,
        conversation_id: str,
        entry_id: str,
        key_id: str,
        ciphertext: bytes,
    ) -> tuple[ChainEntry, bool]:
        """The entry, and whether this call created it: a re-post of the same bytes is answered."""
        if not _ENVELOPE_MIN <= len(ciphertext) <= MAX_AMENDMENT_BYTES or ciphertext[0] != 1:
            raise ArchiveAccessError("bad_ciphertext")
        name = object_key(conversation_id, entry_id, AMENDMENT)
        listed = ChainObject(AMENDMENT, name, len(ciphertext), _sha256(ciphertext))
        existing = await _guard(
            self._repository.existing_amendment(
                tenant_id, sub, conversation_id, entry_id, self._clock()
            )
        )
        if existing is not None:
            return (
                await self._again(tenant_id, conversation_id, existing, listed, ciphertext),
                False,
            )
        if not self._spools.spool(tenant_id).has_room(len(ciphertext)):
            raise ArchiveAccessError("unavailable")
        try:
            entry = await self._commit(tenant_id, sub, conversation_id, entry_id, key_id, listed)
        except ArchiveAccessRefusedError as refused:
            if refused.code == "entry_exists":
                # Two identical posts at once: the other won the insert; answer as a re-post.
                return await self._lost_race(
                    tenant_id, sub, conversation_id, entry_id, listed, ciphertext
                )
            if refused.code != "no_conversation":
                raise ArchiveAccessError(refused.code) from None
            raise await self._not_found(tenant_id, sub, conversation_id) from None
        await self._spool(tenant_id, conversation_id, name, ciphertext)
        return entry, True

    async def _lost_race(
        self,
        tenant_id: str,
        sub: str,
        conversation_id: str,
        entry_id: str,
        listed: ChainObject,
        ciphertext: bytes,
    ) -> tuple[ChainEntry, bool]:
        existing = await _guard(
            self._repository.existing_amendment(
                tenant_id, sub, conversation_id, entry_id, self._clock()
            )
        )
        if existing is None:
            raise ArchiveAccessError("entry_exists")
        return await self._again(tenant_id, conversation_id, existing, listed, ciphertext), False

    async def _again(
        self,
        tenant_id: str,
        conversation_id: str,
        existing: ExistingAmendment,
        listed: ChainObject,
        ciphertext: bytes,
    ) -> ChainEntry:
        """A re-post, after a failure the browser could not tell apart: the same bytes only.

        The chain names the bytes, so anything else is another amendment under a used ID.
        """
        if existing.entry.objects != objects_json([listed]):
            raise ArchiveAccessError("entry_exists")
        if not existing.stored:
            await self._spool(tenant_id, conversation_id, listed.key, ciphertext)
        return existing.entry

    async def _commit(
        self,
        tenant_id: str,
        sub: str,
        conversation_id: str,
        entry_id: str,
        key_id: str,
        listed: ChainObject,
    ) -> ChainEntry:
        now = self._clock()

        def seal(seq: int, prev_hash: bytes) -> ChainEntry:
            return seal_entry(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                seq=seq,
                entry_id=entry_id,
                kind="amendment",
                window_id=None,
                key_id=key_id,
                objects=(listed,),
                prev_hash=prev_hash,
                created_at=now,
                signing_key=self._secrets.signing_key,
                signer_key_id=self._secrets.signing_key_id,
            )

        return await _guard(
            self._repository.append_amendment(
                tenant_id, sub, conversation_id, key_id, now, seal, now
            )
        )

    async def _spool(
        self, tenant_id: str, conversation_id: str, name: str, ciphertext: bytes
    ) -> None:
        spool = self._spools.spool(tenant_id)
        try:
            await asyncio.to_thread(spool.submit, tenant_id, name, ciphertext)
        except SpoolFullError:
            # Committed but not on its way: a gap until the browser re-posts it (§10.5).
            logger.error("recording_amendment_not_spooled")
            try:
                await self._repository.mark_incomplete(tenant_id, conversation_id)
            except RecordingStorageUnavailable:
                logger.error("recording_archive_step_failed step=incomplete")
            raise ArchiveAccessError("write_failed") from None
        finally:
            self._spools.notify(tenant_id)

    async def report(self, tenant_id: str, sub: str, conversation_id: str, stage: str) -> None:
        """A browser's integrity failure (§10.6): a signal, audited and logged with IDs only."""
        if stage not in INTEGRITY_STAGES:
            raise ArchiveAccessError("not_found")
        now = self._clock()
        marker = (tenant_id, sub, conversation_id, stage)
        last = self._reported.get(marker)
        if last is not None and now - last < REPORT_INTERVAL:
            return
        if not await _guard(self._repository.openable(tenant_id, sub, conversation_id, now)):
            raise await self._not_found(tenant_id, sub, conversation_id)
        await _guard(
            self._repository.record_integrity_failure(tenant_id, sub, conversation_id, stage, now)
        )
        self._reported[marker] = now
        logger.warning("recording_archive_integrity_failed stage=%s", stage)
