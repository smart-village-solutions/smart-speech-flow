"""Verification by assigned reviewers (spec §10.7).

The gateway reads the Studio directory live before every grant and decision,
checks every signature the browser made, and leaves the locked checks to the
repository. It never sees a conversation key or a note in clear.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from datetime import datetime
from typing import Protocol, TypeVar

from ..clock import utc_now
from ..studio_recording_directory_client import RecordingDirectory
from .archive_access import ArchiveAccess, ArchiveAccessError
from .crypto import tags
from .crypto.ecies import Sealed, SealedPayloadError
from .crypto.signatures import signed_digest, verify_fields, wrap_fields
from .crypto.verification import notes_digest, verification_fields
from .directory import review_snapshot
from .permissions import REVIEW, REVIEW_SWORN
from .recovery_requests_model import Refused
from .repository import RecordingStorageUnavailable
from .verification_model import (
    ENVELOPE_MIN,
    MAX_NOTE_BYTES,
    MAX_OVERALL_BYTES,
    AssignRequest,
    AssignWrap,
    Candidate,
    DecisionPost,
    InboxRow,
    KeyRow,
    NewAssignment,
    NotePost,
    VerificationRow,
)
from .verification_repository import ReviewOpened

T = TypeVar("T")
MAX_SEALED_CHARACTERS = 2_048


class VerificationError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Directory(Protocol):
    async def snapshot(self, tenant_id: str, correlation_id: str) -> RecordingDirectory | None: ...


class VerificationStore(Protocol):
    async def excluded(
        self, tenant_id: str, conversation_id: str, subs: Sequence[str]
    ) -> frozenset[str]: ...

    async def active_keys(self, tenant_id: str, subs: Sequence[str]) -> dict[str, KeyRow]: ...

    async def assign(
        self, assignment: NewAssignment, now: datetime, *, supervisor: bool
    ) -> Refused | VerificationRow: ...

    async def inbox(self, tenant_id: str, sub: str, now: datetime) -> list[InboxRow]: ...

    async def open_review(
        self, tenant_id: str, sub: str, verification_id: str, now: datetime, *, reviewer: bool
    ) -> ReviewOpened | None: ...

    async def start(
        self,
        tenant_id: str,
        sub: str,
        verification_id: str,
        expected_head_seq: int,
        snapshot: Sequence[str],
        now: datetime,
    ) -> Refused | VerificationRow: ...

    async def save_draft(
        self,
        tenant_id: str,
        sub: str,
        verification_id: str,
        overall: bytes | None,
        notes: Sequence[NotePost],
        now: datetime,
    ) -> Refused | None: ...

    async def decline(
        self, tenant_id: str, sub: str, verification_id: str, now: datetime
    ) -> Refused | None: ...

    async def record_of(
        self, tenant_id: str, sub: str, verification_id: str
    ) -> VerificationRow | None: ...

    async def decide(
        self, tenant_id: str, sub: str, verification_id: str, decision: DecisionPost, now: datetime
    ) -> Refused | VerificationRow: ...


async def _stored(work: Awaitable[T]) -> T:
    try:
        return await work
    except RecordingStorageUnavailable:
        raise VerificationError("unavailable") from None


def _sealed_ephemeral(blob: str) -> bytes | None:
    if len(blob) > MAX_SEALED_CHARACTERS:
        return None
    try:
        return Sealed.from_json(blob, expected_type=tags.CK_WRAP).ephemeral
    except SealedPayloadError:
        return None


def _envelope(data: bytes, limit: int) -> bool:
    return ENVELOPE_MIN <= len(data) <= limit and data[0] == 1


def check_notes(overall: bytes | None, notes: Sequence[NotePost]) -> None:
    """Envelope shape and size only: the gateway cannot read a note (A.3a)."""
    if overall is not None and not _envelope(overall, MAX_OVERALL_BYTES):
        raise VerificationError("bad_notes")
    if len({note.entry_id for note in notes}) != len(notes):
        raise VerificationError("bad_notes")
    if not all(_envelope(note.ciphertext, MAX_NOTE_BYTES) for note in notes):
        raise VerificationError("bad_notes")


def _answer(result: Refused | T) -> T:
    if isinstance(result, Refused):
        raise VerificationError(result.code)
    return result


def wrap_signed(
    tenant_id: str, conversation_id: str, wrap: AssignWrap, signer: KeyRow, reviewer: KeyRow
) -> bool:
    """A browser-made grant: a `ck-wrap` for the reviewer's key, signed by the assigner (A.6)."""
    ephemeral = _sealed_ephemeral(wrap.blob)
    if ephemeral is None:
        return False
    fields = wrap_fields(
        tenant_id,
        conversation_id,
        wrap.key_id,
        ephemeral,
        "user",
        reviewer.sub,
        reviewer.fingerprint,
    )
    return verify_fields(signer.sig_pub, wrap.signature, tags.WRAP_SIG, *fields)


class Verifications:
    def __init__(
        self,
        *,
        store: VerificationStore,
        directory: Directory,
        access: ArchiveAccess,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._store = store
        self._directory = directory
        self._access = access
        self._clock = clock

    async def _read_directory(self, tenant_id: str, correlation_id: str) -> RecordingDirectory:
        directory = await self._directory.snapshot(tenant_id, correlation_id)
        if directory is None:
            raise VerificationError("directory_unavailable")
        return directory

    async def _openable(
        self, tenant_id: str, sub: str, conversation_id: str, supervisor: bool
    ) -> None:
        try:
            await self._access.require_openable(
                tenant_id, sub, conversation_id, supervisor=supervisor
            )
        except ArchiveAccessError as error:
            raise VerificationError(error.code) from None

    async def candidates(
        self,
        tenant_id: str,
        sub: str,
        conversation_id: str,
        correlation_id: str,
        *,
        supervisor: bool,
    ) -> list[Candidate]:
        await self._openable(tenant_id, sub, conversation_id, supervisor)
        directory = await self._read_directory(tenant_id, correlation_id)
        reviewers = directory.holders_of(REVIEW)
        excluded = await _stored(self._store.excluded(tenant_id, conversation_id, list(reviewers)))
        eligible = sorted(set(reviewers) - excluded)
        keys = await _stored(self._store.active_keys(tenant_id, eligible))
        found = [
            Candidate(
                sub=user.sub,
                display_name=user.display_name,
                languages=user.languages,
                sworn=REVIEW_SWORN in user.permissions,
                key=keys[user.sub],
            )
            for user in (reviewers[sub_] for sub_ in eligible)
            if user.sub in keys
        ]
        return sorted(found, key=lambda candidate: (candidate.display_name, candidate.sub))

    async def assign(
        self,
        tenant_id: str,
        sub: str,
        conversation_id: str,
        request: AssignRequest,
        correlation_id: str,
        *,
        supervisor: bool,
    ) -> VerificationRow:
        await self._openable(tenant_id, sub, conversation_id, supervisor)
        directory = await self._read_directory(tenant_id, correlation_id)
        read_at = self._clock()
        if review_snapshot(directory, request.reviewer_sub) is None:
            raise VerificationError("not_a_reviewer")
        keys = await _stored(self._store.active_keys(tenant_id, [sub, request.reviewer_sub]))
        own, reviewer = keys.get(sub), keys.get(request.reviewer_sub)
        if own is None or own.key_version != request.key_version:
            raise VerificationError("key_changed")
        if reviewer is None or reviewer.key_version != request.reviewer_key_version:
            raise VerificationError("reviewer_key_changed")
        if not all(
            wrap_signed(tenant_id, conversation_id, wrap, own, reviewer) for wrap in request.wraps
        ):
            raise VerificationError("signature_invalid")
        assignment = NewAssignment(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            requester_sub=sub,
            requester_key_version=own.key_version,
            reviewer_sub=reviewer.sub,
            reviewer_key_version=reviewer.key_version,
            reviewer_fingerprint=reviewer.fingerprint,
            directory_read_at=read_at,
            wraps=request.wraps,
        )
        result = await _stored(self._store.assign(assignment, self._clock(), supervisor=supervisor))
        if isinstance(result, Refused):
            if result.code == "not_found":
                raise VerificationError(
                    (await self._access.refuse(tenant_id, sub, conversation_id)).code
                )
            raise VerificationError(result.code)
        return result

    async def inbox(self, tenant_id: str, sub: str, correlation_id: str) -> list[InboxRow]:
        rows = await _stored(self._store.inbox(tenant_id, sub, self._clock()))
        subs = {row.requested_by for row in rows}
        names = await self._access.names_of(tenant_id, subs, correlation_id)
        return [replace(row, requested_by_name=names.get(row.requested_by)) for row in rows]

    async def open_review(
        self, tenant_id: str, sub: str, verification_id: str, correlation_id: str
    ) -> ReviewOpened:
        """Only the review routes reach this, behind `ssf.recording.review` (§10.7)."""
        opened = await _stored(
            self._store.open_review(tenant_id, sub, verification_id, self._clock(), reviewer=True)
        )
        if opened is None:
            raise VerificationError("verification_not_found")
        self._access.mark_opened(tenant_id, sub, opened.record.conversation_id)
        requester = opened.record.requested_by
        names = await self._access.names_of(tenant_id, {requester}, correlation_id)
        return replace(opened, requester_name=names.get(requester))

    async def _review_snapshot(
        self, tenant_id: str, sub: str, correlation_id: str
    ) -> tuple[str, ...]:
        directory = await self._read_directory(tenant_id, correlation_id)
        snapshot = review_snapshot(directory, sub)
        if snapshot is None:
            raise VerificationError("not_a_reviewer")
        return snapshot

    async def start(
        self,
        tenant_id: str,
        sub: str,
        verification_id: str,
        expected_head_seq: int,
        correlation_id: str,
    ) -> VerificationRow:
        """Also the way back from PERMISSIONS_CHANGED: a started record gets a fresh snapshot."""
        snapshot = await self._review_snapshot(tenant_id, sub, correlation_id)
        work = self._store.start(
            tenant_id, sub, verification_id, expected_head_seq, snapshot, self._clock()
        )
        return _answer(await _stored(work))

    async def save_draft(
        self,
        tenant_id: str,
        sub: str,
        verification_id: str,
        overall: bytes | None,
        notes: Sequence[NotePost],
    ) -> None:
        check_notes(overall, notes)
        work = self._store.save_draft(
            tenant_id, sub, verification_id, overall, notes, self._clock()
        )
        _answer(await _stored(work))

    async def decline(self, tenant_id: str, sub: str, verification_id: str) -> None:
        _answer(await _stored(self._store.decline(tenant_id, sub, verification_id, self._clock())))

    async def _decidable(self, tenant_id: str, sub: str, verification_id: str) -> VerificationRow:
        record = await _stored(self._store.record_of(tenant_id, sub, verification_id))
        if record is None:
            raise VerificationError("verification_not_found")
        if record.status == "awaiting":
            raise VerificationError("not_started")
        if record.status != "in_review":
            raise VerificationError("verification_closed")
        return record

    async def decide(
        self,
        tenant_id: str,
        sub: str,
        verification_id: str,
        outcome: str,
        overall: bytes | None,
        notes: Sequence[NotePost],
        signature: bytes,
        correlation_id: str,
    ) -> VerificationRow:
        record = await self._decidable(tenant_id, sub, verification_id)
        snapshot = await self._review_snapshot(tenant_id, sub, correlation_id)
        if record.permission_snapshot != snapshot or record.reviewed_head is None:
            raise VerificationError("permissions_changed")
        check_notes(overall, notes)
        key = (await _stored(self._store.active_keys(tenant_id, [sub]))).get(sub)
        if key is None:
            raise VerificationError("key_changed")
        digest = notes_digest(overall, [(n.entry_id, n.key_id, n.ciphertext) for n in notes])
        fields = verification_fields(
            tenant_id,
            verification_id,
            record.conversation_id,
            record.reviewed_head,
            outcome,
            digest,
            snapshot,
        )
        if not verify_fields(key.sig_pub, signature, tags.VERIFICATION_SIG, *fields):
            raise VerificationError("signature_invalid")
        decision = DecisionPost(
            outcome=outcome,
            overall=overall,
            notes=tuple(notes),
            signature=signature,
            notes_digest=digest,
            signed_digest=signed_digest(tags.VERIFICATION_SIG, *fields),
            signer_key_version=key.key_version,
            signer_fingerprint=key.fingerprint,
            snapshot=snapshot,
            reviewed_head=record.reviewed_head,
        )
        work = self._store.decide(tenant_id, sub, verification_id, decision, self._clock())
        return _answer(await _stored(work))
