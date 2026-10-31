"""An in-memory archive for tests of recording above the database (spec §11, §13).

`MemoryArchiveRepository` keeps the promises PostgresArchiveRepository's
tables enforce, which tests/integration/test_recording_archive_database.py
checks against the real migration: one transaction per call, a unique `seq`
per conversation, append-only entries and stored objects, one stamp per head.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from services.api_gateway.recording.archive_repository import (
    ConversationRecord,
    NewKey,
    PendingStamp,
    WindowOpening,
)
from services.api_gateway.recording.archive_service import (
    ConversationArchive,
    stored_recorder,
)
from services.api_gateway.recording.audit import AuditEvent
from services.api_gateway.recording.ceremony_model import RecoveryKeyRecord
from services.api_gateway.recording.chain import ChainEntry, object_types
from services.api_gateway.recording.consent_evidence import GuestAnswer
from services.api_gateway.recording.crypto import aead, ecies, tags
from services.api_gateway.recording.repository import RecordingStorageUnavailable, UserKeyRecord
from services.api_gateway.recording.secrets import RecordingSecrets, ServerLayer, gateway_key_id
from services.api_gateway.recording.session_service import (
    RecordingSessions,
    RecordingUnavailableError,
)
from services.api_gateway.recording.session_state import RecordingConflictError, RecordingState
from services.api_gateway.recording.storage.filesystem import FilesystemArchiveStore
from services.api_gateway.recording.storage.tenant_spools import TenantSpools
from services.api_gateway.tenant_session import TenantSessionKey
from tests import recording_crypto_reference as ref

GATEWAY_SCALAR = 7
RECOVERY_SCALAR = 31
EMPLOYEE_SCALAR = 21


def gateway_secrets() -> RecordingSecrets:
    public = ref.public_point(GATEWAY_SCALAR)
    return RecordingSecrets(
        signing_key=ref.private_key(GATEWAY_SCALAR),
        signing_key_id=gateway_key_id(public),
        signing_public_key=public,
        server_layer=ServerLayer(bytes(32)),
    )


def recovery_record(tenant_id: str) -> RecoveryKeyRecord:
    return RecoveryKeyRecord(
        tenant_id=tenant_id,
        key_id="5d1f3a2b-0000-4000-8000-00000000000a",
        recovery_public_key=ref.public_point(RECOVERY_SCALAR),
        k=1,
        n=2,
        mode="standard",
        transcript_hash=b"\x31" * 32,
        canary_wrap="{}",
        canary_signature=bytes(64),
        canary_signer_key_id="gk-x",
        activated_at=datetime(2026, 10, 1),
    )


def employee_record(tenant_id: str, user_sub: str) -> UserKeyRecord:
    return UserKeyRecord(
        tenant_id=tenant_id,
        user_sub=user_sub,
        key_version=1,
        enc_pub=ref.public_point(EMPLOYEE_SCALAR),
        sig_pub=ref.public_point(EMPLOYEE_SCALAR + 1),
        fingerprint=b"\x21" * 32,
        encrypted_private=None,
        created_at=datetime(2026, 10, 1),
    )


@dataclass
class MemoryArchiveRepository:
    conversations: dict[str, ConversationRecord] = field(default_factory=dict)
    windows: dict[str, dict[str, Any]] = field(default_factory=dict)
    keys: dict[str, NewKey] = field(default_factory=dict)
    entries: dict[str, list[ChainEntry]] = field(default_factory=dict)
    stored: dict[tuple[str, str], str] = field(default_factory=dict)
    stamps: dict[tuple[str, int], dict[str, Any]] = field(default_factory=dict)
    audit: list[AuditEvent] = field(default_factory=list)
    incomplete: set[str] = field(default_factory=set)
    ended: dict[str, datetime] = field(default_factory=dict)
    down: bool = False
    # The next write commits, then reports failure: a connection lost during COMMIT.
    lands_then_fails: bool = False

    def _check(self) -> None:
        if self.down:
            raise RecordingStorageUnavailable("down")

    def _landed(self) -> None:
        if self.lands_then_fails:
            self.lands_then_fails = False
            raise RecordingStorageUnavailable("connection lost during commit")

    def _add_entry(self, entry: ChainEntry) -> None:
        chain = self.entries.setdefault(entry.conversation_id, [])
        if any(existing.seq == entry.seq for existing in chain):
            raise RecordingStorageUnavailable("duplicate seq")
        chain.append(entry)

    async def open_window(self, opening: WindowOpening) -> None:
        self._check()
        conversation = opening.conversation
        if opening.new_conversation:
            if conversation.conversation_id in self.conversations:
                raise RecordingStorageUnavailable("duplicate conversation")
            self.conversations[conversation.conversation_id] = conversation
        self.windows[opening.window_id] = {
            "pauses": [],
            "closed": None,
            "conversation": conversation.conversation_id,
        }
        if opening.key is not None:
            self.keys[opening.key.key_id] = opening.key
        self._add_entry(opening.consent)
        self.audit.append(opening.audit)
        self._landed()

    async def append_entry(self, entry: ChainEntry, key: NewKey | None) -> None:
        self._check()
        if key is not None:
            self.keys[key.key_id] = key
        self._add_entry(entry)
        self._landed()

    async def conversation(self, tenant_id: str, conversation_id: str) -> ConversationRecord | None:
        self._check()
        found = self.conversations.get(conversation_id)
        return found if found is not None and found.tenant_id == tenant_id else None

    async def chain_state(self, tenant_id: str, conversation_id: str) -> tuple[int, bytes, int]:
        self._check()
        chain = self.entries.get(conversation_id, [])
        epochs = [
            key.epoch
            for key in self.keys.values()
            if any(entry.key_id == key.key_id for entry in chain)
        ]
        if not chain:
            return 0, bytes(32), max(epochs, default=0)
        return chain[-1].seq, chain[-1].hash, max(epochs, default=0)

    def chain(self, conversation_id: str) -> list[ChainEntry]:
        return list(self.entries.get(conversation_id, []))

    def entry(self, entry_id: str) -> ChainEntry | None:
        for chain in self.entries.values():
            for entry in chain:
                if entry.entry_id == entry_id:
                    return entry
        return None

    async def record_stored(
        self, tenant_id: str, entry_id: str, object_type: str, version_id: str, at: datetime
    ) -> bool:
        self._check()
        if self.entry(entry_id) is None:
            return False
        self.stored.setdefault((entry_id, object_type), version_id)
        return True

    def is_stored(self, entry: ChainEntry) -> bool:
        return all((entry.entry_id, kind) in self.stored for kind in object_types(entry.objects))

    async def note_pause(self, tenant_id, conversation_id, window_id, at, reason) -> None:
        self._check()
        self.windows[window_id]["pauses"].append({"reason": reason, "resumed_at": None})
        self.incomplete.add(conversation_id)

    async def note_resume(self, tenant_id, window_id, at) -> None:
        self._check()
        pauses = self.windows[window_id]["pauses"]
        if pauses:
            pauses[-1]["resumed_at"] = at

    async def mark_incomplete(self, tenant_id, conversation_id) -> None:
        self._check()
        self.incomplete.add(conversation_id)

    async def ping(self, tenant_id) -> None:
        self._check()

    def _request_stamp(self, conversation_id: str, at: datetime) -> None:
        chain = self.entries.get(conversation_id)
        if chain:
            head = chain[-1]
            self.stamps.setdefault(
                (conversation_id, head.seq),
                {"hash": head.hash, "token": None, "attempts": 0, "next": at},
            )

    async def close_window(self, tenant_id, conversation_id, window_id, at, reason) -> None:
        self._check()
        window = self.windows[window_id]
        if window["closed"] is None:
            window["closed"] = reason
        self._request_stamp(conversation_id, at)

    async def open_conversations(self, tenant_id) -> list[tuple[str, str]]:
        self._check()
        return [
            (conversation_id, conversation.session_ref)
            for conversation_id, conversation in self.conversations.items()
            if conversation.tenant_id == tenant_id and conversation_id not in self.ended
        ]

    async def end_conversation(self, tenant_id, conversation_id, at) -> None:
        self._check()
        self.ended.setdefault(conversation_id, at)
        for window in self.windows.values():
            if window["conversation"] == conversation_id and window["closed"] is None:
                window["closed"] = "session_ended"
        self._request_stamp(conversation_id, at)

    async def pending_stamps(self, tenant_id: str, now: datetime) -> list[PendingStamp]:
        self._check()
        due = []
        for (conversation_id, seq), stamp in self.stamps.items():
            conversation = self.conversations[conversation_id]
            if conversation.tenant_id != tenant_id or stamp["token"] is not None:
                continue
            chain = [e for e in self.entries[conversation_id] if e.seq <= seq]
            if stamp["next"] <= now and all(self.is_stored(entry) for entry in chain):
                due.append(
                    PendingStamp(
                        conversation_id,
                        seq,
                        stamp["hash"],
                        conversation.timestamp_authority_url,
                        stamp["attempts"],
                    )
                )
        return due

    async def save_stamp(self, tenant_id, stamp, token, stamped_at) -> None:
        self._check()
        row = self.stamps[(stamp.conversation_id, stamp.head_seq)]
        row.update(token=token, attempts=row["attempts"] + 1)

    async def defer_stamp(self, tenant_id, stamp, next_attempt_at) -> None:
        self._check()
        row = self.stamps[(stamp.conversation_id, stamp.head_seq)]
        row.update(attempts=row["attempts"] + 1, next=next_attempt_at)


@dataclass
class ArchiveRig:
    archive: ConversationArchive
    repository: MemoryArchiveRepository
    spools: TenantSpools
    store: FilesystemArchiveStore
    secrets: RecordingSecrets
    recovery_present: bool = True
    employee_enrolled: bool = True
    writer_ready: bool = True
    # Session IDs the session store still lists as not ended; None: it cannot be read.
    live_sessions: set[str] | None = field(default_factory=set)


def archive_rig(
    root: Path,
    clock: Callable[[], datetime],
    *,
    capacity_bytes: int = 1 << 30,
    headroom_bytes: int = 8 << 20,
) -> ArchiveRig:
    repository = MemoryArchiveRepository()
    store = FilesystemArchiveStore(root / "store", timedelta(days=2))
    spools = TenantSpools(
        root / "spool",
        store,
        stored_recorder(repository, clock),
        capacity_bytes=capacity_bytes,
        headroom_bytes=headroom_bytes,
    )
    secrets = gateway_secrets()
    rig: ArchiveRig

    async def recovery_key(tenant_id: str) -> RecoveryKeyRecord | None:
        return recovery_record(tenant_id) if rig.recovery_present else None

    async def live_sessions(tenant_id: str) -> set[str]:
        if rig.live_sessions is None:
            raise ConnectionError("session store down")
        return rig.live_sessions

    async def user_key(tenant_id: str, user_sub: str) -> UserKeyRecord | None:
        return employee_record(tenant_id, user_sub) if rig.employee_enrolled else None

    archive = ConversationArchive(
        repository=repository,
        spools=spools,
        secrets=secrets,
        recovery_key=recovery_key,
        user_key=user_key,
        session_ref=lambda session_id: f"ref-{session_id}",
        tenant_ready=lambda _tenant_id: rig.writer_ready,
        live_sessions=live_sessions,
        clock=clock,
    )
    rig = ArchiveRig(archive, repository, spools, store, secrets)
    return rig


def decoded_objects(entry: ChainEntry) -> list[dict[str, Any]]:
    return json.loads(entry.objects)


def conversation_key(rig: ArchiveRig, entry: ChainEntry, *, scalar: int = RECOVERY_SCALAR) -> bytes:
    """Unwrap the entry's conversation key as the recovery or the employee key would (#616)."""
    new_key = rig.repository.keys[entry.key_id]
    kind = "recovery" if scalar == RECOVERY_SCALAR else "user"
    wrap = next(w for w in new_key.wraps if w.recipient_kind == kind)
    context = ecies.ck_wrap_context(
        entry.tenant_id, entry.conversation_id, entry.key_id, kind, wrap.recipient_ref
    )
    sealed = ecies.Sealed.from_json(wrap.blob, expected_type=tags.CK_WRAP)
    return ecies.open_with_private_key(sealed, ref.private_key(scalar), context)


async def open_object(
    rig: ArchiveRig, entry: ChainEntry, object_type: str, *, scalar: int = RECOVERY_SCALAR
) -> bytes:
    """Upload what is spooled, then read an entry's object by its version ID and open it."""
    assert await rig.spools.flush()
    listed = next(o for o in decoded_objects(entry) if o["type"] == object_type)
    version_id = rig.repository.stored[(entry.entry_id, object_type)]
    ciphertext = await rig.store.get(entry.tenant_id, listed["key"], version_id)
    aad = aead.object_aad(
        entry.tenant_id, entry.conversation_id, entry.entry_id, object_type, entry.key_id
    )
    return aead.open_(conversation_key(rig, entry, scalar=scalar), ciphertext, aad)


GUEST_NAME = "Amira Haddad"


async def say_yes(
    service: RecordingSessions,
    key: TenantSessionKey,
    request_id: str,
    *,
    language: str = "en",
    name: str | None = GUEST_NAME,
    signature_png: bytes | None = None,
    cannot_sign: bool = False,
    documentation_consent: bool = True,
) -> RecordingState:
    """A guest's yes as the screen sends it: the hash of the text it was served, and a name."""
    try:
        digest: str | None = (await service.consent(key, language)).text.answer_sha256
    except (RecordingConflictError, RecordingUnavailableError):
        digest = None  # no open question: the answer itself meets the refusal
    reply = GuestAnswer(
        language,
        digest,
        name=name,
        signature_png=signature_png,
        cannot_sign=cannot_sign,
        documentation_consent=documentation_consent,
    )
    return await service.answer(key, request_id=request_id, consent=True, reply=reply)
