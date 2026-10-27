"""Archiving what a recorded conversation says (spec §7, §8.1, §11, §12.3).

`ConversationArchive` holds what must never leave the gateway's memory, the
conversation keys, and the chain head of each conversation. `RecordingSessions`
calls it under the conversation's session lock only, so entries are decided,
numbered and linked in one order. For each entry it encrypts the objects,
signs the entry, commits it to the database, and only then hands the
ciphertext to the tenant's spool; the uploader confirms each object later.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Final, Protocol

from ..clock import utc_now
from ..session_models import ClientType
from ..studio_v2 import RecordingPolicy
from ..tenant_session import TenantSessionKey
from . import records
from .archive_repository import (
    ConversationRecord,
    NewKey,
    PendingStamp,
    WindowOpening,
)
from .audit import AuditEvent
from .ceremony_model import RecoveryKeyRecord
from .chain import ChainEntry, ChainObject, EntryKind, seal_entry
from .conversation_keys import (
    ConversationKey,
    Recipient,
    new_conversation_key,
    seal_object,
    wrap_key,
)
from .repository import RecordingStorageUnavailable, UserKeyRecord
from .secrets import RecordingSecrets
from .session_state import Phase, RecordingState
from .storage.archive import object_key
from .storage.spool import SpoolFullError, SpoolItem, StoredVersion
from .storage.tenant_spools import TenantSpools
from .timestamps import TimestampAuthority, TimestampError

logger = logging.getLogger(__name__)

GUEST_ACTOR: Final[str] = "guest"
STAMP_RETRY_INITIAL: Final[timedelta] = timedelta(seconds=30)
STAMP_RETRY_CEILING: Final[timedelta] = timedelta(hours=6)


class ArchiveUnavailableError(Exception):
    """This entry could not be archived; nothing of it was committed unless `committed`."""

    def __init__(self, code: str, *, committed: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.committed = committed


class ArchiveRepository(Protocol):
    async def open_window(self, opening: WindowOpening) -> None: ...

    async def append_entry(self, entry: ChainEntry, key: NewKey | None) -> None: ...

    async def conversation(
        self, tenant_id: str, conversation_id: str
    ) -> ConversationRecord | None: ...

    async def chain_state(self, tenant_id: str, conversation_id: str) -> tuple[int, bytes, int]: ...

    async def record_stored(
        self, tenant_id: str, entry_id: str, object_type: str, version_id: str, at: datetime
    ) -> bool: ...

    async def note_pause(
        self, tenant_id: str, conversation_id: str, window_id: str, at: datetime, reason: str
    ) -> None: ...

    async def note_resume(self, tenant_id: str, window_id: str, at: datetime) -> None: ...

    async def mark_incomplete(self, tenant_id: str, conversation_id: str) -> None: ...

    async def close_window(
        self, tenant_id: str, conversation_id: str, window_id: str, at: datetime, reason: str
    ) -> None: ...

    async def end_conversation(
        self, tenant_id: str, conversation_id: str, at: datetime
    ) -> None: ...

    async def pending_stamps(self, tenant_id: str, now: datetime) -> list[PendingStamp]: ...

    async def save_stamp(
        self, tenant_id: str, stamp: PendingStamp, token: bytes, stamped_at: datetime
    ) -> None: ...

    async def defer_stamp(
        self, tenant_id: str, stamp: PendingStamp, next_attempt_at: datetime
    ) -> None: ...


@dataclass(frozen=True)
class MessageArtefacts:
    """One processed message as the pipeline left it, before it is delivered."""

    message_id: str
    sender: ClientType
    source_lang: str
    target_lang: str
    source_text: str | None
    result: Mapping[str, Any]
    original_audio: bytes | None
    accepted_at: datetime

    @property
    def failed(self) -> bool:
        return bool(self.result.get("error"))

    @property
    def translated_audio(self) -> bytes | None:
        return None if self.failed else self.result.get("audio_bytes") or None


@dataclass(frozen=True)
class _Archived:
    entry_id: str
    sender: ClientType


@dataclass(frozen=True)
class _Head:
    seq: int
    hash: bytes


@dataclass(frozen=True)
class _Sealed:
    """An entry ready to commit, with its ciphertexts and what memory learns once it is."""

    entry: ChainEntry
    blobs: tuple[tuple[str, bytes], ...]
    key: ConversationKey
    new_key: NewKey | None


class ConversationArchive:
    def __init__(
        self,
        *,
        repository: ArchiveRepository,
        spools: TenantSpools,
        secrets: RecordingSecrets,
        recovery_key: Callable[[str], Awaitable[RecoveryKeyRecord | None]],
        user_key: Callable[[str, str], Awaitable[UserKeyRecord | None]],
        session_ref: Callable[[str], str],
        tenant_ready: Callable[[str], bool] = lambda _tenant_id: True,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository = repository
        self._spools = spools
        self._secrets = secrets
        self._recovery_key = recovery_key
        self._user_key = user_key
        self._session_ref = session_ref
        self._tenant_ready = tenant_ready
        self._clock = clock
        # Memory only (§8.1): a restart loses them, and the next entry starts a new epoch.
        self._keys: dict[tuple[str, str], ConversationKey] = {}
        self._heads: dict[tuple[str, str], _Head] = {}
        # A conversation chosen at a yes whose state may not have been saved, so a
        # retried yes continues it instead of opening a second one.
        self._opened: dict[TenantSessionKey, str] = {}
        self._entries: dict[TenantSessionKey, dict[str, _Archived]] = {}
        self._played: dict[TenantSessionKey, set[tuple[str, str]]] = {}
        self._pending_ends: dict[tuple[str, str], datetime] = {}

    def can_record(self, tenant_id: str) -> bool:
        """Whether this tenant's objects can leave the gateway at all: it has a writer credential."""
        return self._tenant_ready(tenant_id)

    def ready(self, key: TenantSessionKey) -> bool:
        return self._spools.ready(key.tenant_id)

    async def open_window(
        self,
        key: TenantSessionKey,
        before: RecordingState,
        after: RecordingState,
        policy: RecordingPolicy,
    ) -> RecordingState:
        """A guest's yes: conversation, window, key, consent entry and audit, or none of them.

        Once that transaction has committed, the yes stands: a spool write that
        fails afterwards marks the conversation incomplete, as for any entry.
        """
        now = self._clock()
        conversation, new_conversation, fresh = await self._opening_conversation(
            key, before, policy, now
        )
        window_id = after.window_id or ""
        consent = records.consent_record(
            request_id=before.request_id or "",
            request_kind=before.request_kind or "first",
            requested_by=before.requested_by or "",
            requested_at=before.since,
            answered_at=now,
            window_id=window_id,
            legal_basis=policy.legal_basis,
        )
        sealed = await self._seal(
            conversation,
            "consent",
            window_id,
            {"consent.json": records.encode(consent)},
            now,
            fresh=fresh,
        )
        opening = WindowOpening(
            conversation=conversation,
            new_conversation=new_conversation,
            window_id=window_id,
            opened_at=now,
            key=sealed.new_key,
            consent=sealed.entry,
            audit=AuditEvent(key.tenant_id, GUEST_ACTOR, "recording.arming", window_id, now),
        )
        await self._commit(sealed, self._repository.open_window(opening))
        try:
            await self._spool(key.tenant_id, conversation.conversation_id, sealed.blobs)
        except ArchiveUnavailableError as error:
            logger.error("recording_consent_not_spooled tenant_ref=%s", key.tenant_ref)
            if not error.committed:
                raise
        return replace(after, conversation_id=conversation.conversation_id)

    async def _opening_conversation(
        self,
        key: TenantSessionKey,
        before: RecordingState,
        policy: RecordingPolicy,
        now: datetime,
    ) -> tuple[ConversationRecord, bool, bool]:
        """(conversation, whether to insert it, whether its chain is known to be empty)."""
        conversation_id = before.conversation_id or self._opened.get(key)
        if conversation_id is not None:
            try:
                existing = await self._repository.conversation(key.tenant_id, conversation_id)
            except RecordingStorageUnavailable:
                raise ArchiveUnavailableError("database") from None
            if existing is not None:
                return existing, False, False
            if before.conversation_id is not None:
                raise ArchiveUnavailableError("no_conversation")
        else:
            conversation_id = str(uuid.uuid4())
            self._opened[key] = conversation_id
        conversation = ConversationRecord(
            tenant_id=key.tenant_id,
            conversation_id=conversation_id,
            session_ref=self._session_ref(key.session_id),
            employee_sub=before.requested_by or "",
            legal_basis=policy.legal_basis,
            timestamp_authority_url=str(policy.timestamp_authority_url),
            started_at=now,
            retention_until=now + timedelta(hours=policy.retention_hours),
        )
        return conversation, True, True

    async def archive_message(
        self, key: TenantSessionKey, state: RecordingState, artefacts: MessageArtefacts
    ) -> str:
        """Under the session lock, once the §5.3 decision said yes. Returns the entry ID."""
        conversation = await self._conversation(key.tenant_id, state.conversation_id)
        now = self._clock()
        record = records.message_record(
            message_id=artefacts.message_id,
            sender=artefacts.sender.value,
            source_lang=artefacts.source_lang,
            target_lang=artefacts.target_lang,
            source_text=artefacts.source_text,
            result=artefacts.result,
            original_audio=artefacts.original_audio,
            translated_audio=artefacts.translated_audio,
            accepted_at=artefacts.accepted_at,
            completed_at=now,
        )
        plaintexts = {"record.json": records.encode(record)}
        if artefacts.original_audio is not None:
            plaintexts["original.wav"] = artefacts.original_audio
        if artefacts.translated_audio is not None:
            plaintexts["translated.wav"] = artefacts.translated_audio
        kind: EntryKind = "failed" if artefacts.failed else "message"
        sealed = await self._seal(conversation, kind, state.window_id, plaintexts, now)
        await self._commit(sealed, self._repository.append_entry(sealed.entry, sealed.new_key))
        self._entries.setdefault(key, {})[artefacts.message_id] = _Archived(
            sealed.entry.entry_id, artefacts.sender
        )
        if artefacts.failed:
            await _best_effort(
                "incomplete",
                self._repository.mark_incomplete(key.tenant_id, conversation.conversation_id),
            )
        await self._spool(key.tenant_id, conversation.conversation_id, sealed.blobs)
        return sealed.entry.entry_id

    def archived_entry(self, key: TenantSessionKey, message_id: str) -> str | None:
        archived = self._entries.get(key, {}).get(message_id)
        return None if archived is None else archived.entry_id

    async def archive_playback(
        self,
        key: TenantSessionKey,
        state: RecordingState,
        message_id: str,
        event: records.PlaybackEvent,
        reported_by: ClientType,
    ) -> bool:
        """A playback report of an archived message; False when it is not archived.

        Only the receiving screen reports, and each event of a message counts
        once, so a screen cannot fill the chain with reports.
        """
        archived = self._entries.get(key, {}).get(message_id)
        played = self._played.setdefault(key, set())
        if archived is None or archived.sender is reported_by or (message_id, event) in played:
            return False
        entry_id = archived.entry_id
        conversation = await self._conversation(key.tenant_id, state.conversation_id)
        now = self._clock()
        record = records.playback_record(
            message_id=message_id,
            message_entry_id=entry_id,
            event=event,
            reported_by=reported_by.value,
            at=now,
        )
        sealed = await self._seal(
            conversation,
            "playback",
            state.window_id,
            {"playback.json": records.encode(record)},
            now,
        )
        await self._commit(sealed, self._repository.append_entry(sealed.entry, sealed.new_key))
        played.add((message_id, event))
        await self._spool(key.tenant_id, conversation.conversation_id, sealed.blobs)
        return True

    async def declined(self, key: TenantSessionKey, before: RecordingState) -> None:
        """A "no" to a resume, after an earlier yes: its own consent entry (§6). Best effort."""
        conversation = await self._conversation(key.tenant_id, before.conversation_id)
        now = self._clock()
        record = records.consent_record(
            request_id=before.request_id or "",
            request_kind=before.request_kind or "resume",
            requested_by=before.requested_by or "",
            requested_at=before.since,
            answered_at=now,
            window_id=None,
            legal_basis=conversation.legal_basis,
            answer="no",
        )
        sealed = await self._seal(
            conversation, "consent", None, {"consent.json": records.encode(record)}, now
        )
        await self._commit(sealed, self._repository.append_entry(sealed.entry, sealed.new_key))
        await self._spool(key.tenant_id, conversation.conversation_id, sealed.blobs)

    async def transitioned(
        self, key: TenantSessionKey, before: RecordingState, after: RecordingState
    ) -> None:
        """Pauses and closes of a window, kept beside it. A failure is logged, never raised."""
        if before.phase is Phase.ASKING and after.answer is False and before.consented:
            try:
                await self.declined(key, before)
            except ArchiveUnavailableError as error:
                logger.error("recording_decline_not_archived code=%s", error.code)
            return
        conversation_id, window_id = after.conversation_id, before.window_id
        if conversation_id is None or window_id is None:
            return
        now = self._clock()
        reason = after.reason.value if after.reason else ""
        if after.phase is Phase.PAUSED and before.phase is not Phase.PAUSED:
            await _best_effort(
                "pause",
                self._repository.note_pause(key.tenant_id, conversation_id, window_id, now, reason),
            )
        elif after.phase is Phase.ON and before.phase is Phase.PAUSED:
            await _best_effort(
                "resume", self._repository.note_resume(key.tenant_id, window_id, now)
            )
        elif after.phase is Phase.OFF and before.recording:
            await _best_effort(
                "close",
                self._repository.close_window(
                    key.tenant_id, conversation_id, window_id, now, reason
                ),
            )

    async def session_ended(self, key: TenantSessionKey, state: RecordingState) -> None:
        """The end of the conversation: its keys are dropped, its head queued for a stamp."""
        conversation_id = state.conversation_id or self._opened.get(key)
        self._opened.pop(key, None)
        self._entries.pop(key, None)
        self._played.pop(key, None)
        if conversation_id is None:
            return
        self._forget(key.tenant_id, conversation_id)
        ending = (key.tenant_id, conversation_id)
        self._pending_ends[ending] = self._clock()
        await self._end(ending)

    async def retry_pending_ends(self) -> None:
        """Ends the database missed, written now: an unwritten end leaves the chain unstamped."""
        for ending in list(self._pending_ends):
            await self._end(ending)

    async def _end(self, ending: tuple[str, str]) -> None:
        tenant_id, conversation_id = ending
        at = self._pending_ends[ending]
        if await _best_effort(
            "end", self._repository.end_conversation(tenant_id, conversation_id, at)
        ):
            self._pending_ends.pop(ending, None)

    def _forget(self, tenant_id: str, conversation_id: str) -> None:
        self._keys.pop((tenant_id, conversation_id), None)
        self._heads.pop((tenant_id, conversation_id), None)

    async def _conversation(
        self, tenant_id: str, conversation_id: str | None
    ) -> ConversationRecord:
        if conversation_id is None:
            raise ArchiveUnavailableError("no_conversation")
        try:
            conversation = await self._repository.conversation(tenant_id, conversation_id)
        except RecordingStorageUnavailable:
            raise ArchiveUnavailableError("database") from None
        if conversation is None:
            raise ArchiveUnavailableError("no_conversation")
        return conversation

    async def _seal(
        self,
        conversation: ConversationRecord,
        kind: EntryKind,
        window_id: str | None,
        plaintexts: Mapping[str, bytes],
        now: datetime,
        *,
        fresh: bool = False,
    ) -> _Sealed:
        tenant_id, conversation_id = conversation.tenant_id, conversation.conversation_id
        head, epoch = await self._head(tenant_id, conversation_id, fresh=fresh)
        key, new_key = await self._key(conversation, epoch, now)
        entry_id = str(uuid.uuid4())
        objects, blobs = [], []
        for object_type, plaintext in sorted(plaintexts.items()):
            ciphertext = seal_object(
                key,
                plaintext,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                entry_id=entry_id,
                object_type=object_type,
            )
            name = object_key(conversation_id, entry_id, object_type)
            objects.append(ChainObject(object_type, name, len(ciphertext), _sha256(ciphertext)))
            blobs.append((name, ciphertext))
        # Checked before anything is committed: an entry the spool cannot take is not decided.
        if not self._spools.spool(tenant_id).has_room(sum(len(data) for _, data in blobs)):
            raise ArchiveUnavailableError("spool_full")
        entry = seal_entry(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            seq=head.seq + 1,
            entry_id=entry_id,
            kind=kind,
            window_id=window_id,
            key_id=key.key_id,
            objects=objects,
            prev_hash=head.hash,
            created_at=now,
            signing_key=self._secrets.signing_key,
            signer_key_id=self._secrets.signing_key_id,
        )
        return _Sealed(entry, tuple(blobs), key, new_key)

    async def _head(
        self, tenant_id: str, conversation_id: str, *, fresh: bool
    ) -> tuple[_Head, int]:
        """The chain head and the highest key epoch, from memory or, after a restart, the database.

        Memory holds both or neither: they are set together once an entry commits.
        """
        if fresh:
            return _Head(0, bytes(32)), 0
        cached = self._heads.get((tenant_id, conversation_id))
        if cached is not None and (tenant_id, conversation_id) in self._keys:
            return cached, self._keys[(tenant_id, conversation_id)].epoch
        try:
            seq, head_hash, epoch = await self._repository.chain_state(tenant_id, conversation_id)
        except RecordingStorageUnavailable:
            raise ArchiveUnavailableError("database") from None
        return _Head(seq, head_hash), epoch

    async def _key(
        self, conversation: ConversationRecord, epoch: int, now: datetime
    ) -> tuple[ConversationKey, NewKey | None]:
        known = self._keys.get((conversation.tenant_id, conversation.conversation_id))
        if known is not None:
            return known, None
        key = new_conversation_key(epoch + 1)
        recipients = await self._recipients(conversation)
        wraps = tuple(
            wrap_key(
                key,
                recipient,
                tenant_id=conversation.tenant_id,
                conversation_id=conversation.conversation_id,
                signing_key=self._secrets.signing_key,
                signer_key_id=self._secrets.signing_key_id,
            )
            for recipient in recipients
        )
        return key, NewKey(key.key_id, key.epoch, now, wraps)

    async def _recipients(self, conversation: ConversationRecord) -> list[Recipient]:
        """The recovery key always; the employee too once enrolled (§8.1)."""
        try:
            recovery = await self._recovery_key(conversation.tenant_id)
            employee = await self._user_key(conversation.tenant_id, conversation.employee_sub)
        except RecordingStorageUnavailable:
            raise ArchiveUnavailableError("database") from None
        if recovery is None:
            raise ArchiveUnavailableError("recovery_key_missing")
        recipients = [
            Recipient(
                "recovery", recovery.key_id, recovery.recovery_public_key, recovery.transcript_hash
            )
        ]
        if employee is not None:
            recipients.append(
                Recipient("user", employee.user_sub, employee.enc_pub, employee.fingerprint)
            )
        return recipients

    async def _commit(self, sealed: _Sealed, write: Awaitable[None]) -> None:
        entry = sealed.entry
        try:
            await write
        except BaseException as error:
            # The write may have landed even so (a connection lost during COMMIT,
            # a timeout): memory no longer knows the head, so the next entry reads
            # it from the database and starts a new key epoch.
            self._forget(entry.tenant_id, entry.conversation_id)
            if isinstance(error, RecordingStorageUnavailable):
                raise ArchiveUnavailableError("database") from None
            raise
        conversation = (entry.tenant_id, entry.conversation_id)
        self._keys[conversation] = sealed.key
        self._heads[conversation] = _Head(entry.seq, entry.hash)

    async def _spool(
        self, tenant_id: str, conversation_id: str, blobs: Iterable[tuple[str, bytes]]
    ) -> None:
        spool = self._spools.spool(tenant_id)
        try:
            for name, data in blobs:
                await asyncio.to_thread(spool.submit, tenant_id, name, data)
        except SpoolFullError:
            # Committed but never to arrive: the entry stays pending_upload, and says so.
            await _best_effort(
                "incomplete", self._repository.mark_incomplete(tenant_id, conversation_id)
            )
            raise ArchiveUnavailableError("spool_write", committed=True) from None
        finally:
            self._spools.notify(tenant_id)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def _best_effort(step: str, work: Awaitable[None]) -> bool:
    """For records kept beside the chain: a failure is logged, and recording goes on."""
    try:
        await work
    except RecordingStorageUnavailable:
        logger.error("recording_archive_step_failed step=%s", step)
        return False
    return True


def stored_recorder(
    repository: ArchiveRepository, clock: Callable[[], datetime] = utc_now
) -> Callable[[SpoolItem, StoredVersion], Awaitable[None]]:
    """The uploader's confirmation: one `stored_objects` row per object the store holds."""

    async def on_stored(item: SpoolItem, stored: StoredVersion) -> None:
        _, entry_id, object_type = item.key.split("/")
        if not await repository.record_stored(
            item.tenant_id, entry_id, object_type, stored.version_id, clock()
        ):
            logger.error("recording_object_without_entry seq=%s", item.seq)

    return on_stored


class ChainStamper:
    """Requests RFC 3161 tokens for chain heads whose entries are all stored (§11.2)."""

    def __init__(
        self,
        repository: ArchiveRepository,
        authority: TimestampAuthority,
        tenants: Callable[[], Iterable[str]],
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository = repository
        self._authority = authority
        self._tenants = tenants
        self._clock = clock

    async def run_once(self) -> None:
        for tenant_id in self._tenants():
            try:
                due = await self._repository.pending_stamps(tenant_id, self._clock())
            except RecordingStorageUnavailable:
                continue  # this tenant's turn comes again in the next pass
            for stamp in due:
                await self._stamp(tenant_id, stamp)

    async def _stamp(self, tenant_id: str, stamp: PendingStamp) -> None:
        try:
            token = await self._authority.stamp(stamp.url, stamp.head_hash)
        except Exception as error:  # an authority's answer must never stop the others' stamps
            code = error.code if isinstance(error, TimestampError) else type(error).__name__
            delay = min(STAMP_RETRY_INITIAL * (2**stamp.attempts), STAMP_RETRY_CEILING)
            logger.warning("recording_stamp_deferred code=%s attempts=%s", code, stamp.attempts)
            await _best_effort(
                "defer_stamp",
                self._repository.defer_stamp(tenant_id, stamp, self._clock() + delay),
            )
            return
        await _best_effort(
            "save_stamp", self._repository.save_stamp(tenant_id, stamp, token.token, token.gen_time)
        )
