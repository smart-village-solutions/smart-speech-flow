"""Records and limits of verification by assigned reviewers (spec §10.7)."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

OPEN: Final[frozenset[str]] = frozenset({"awaiting", "in_review"})
DECIDED: Final[frozenset[str]] = frozenset({"approved", "not_approved"})
CATEGORIES: Final[frozenset[str]] = frozenset(
    {
        "translation_error",
        "omission",
        "asr_error",
        "meaning_altered",
        "misunderstanding",
        "suggestion",
        "limitation",
    }
)
# Envelopes (A.3a): version byte, nonce and tag around at most 64 KiB / 32 KiB.
ENVELOPE_MIN: Final[int] = 1 + 12 + 16
MAX_NOTE_BYTES: Final[int] = 65_536 + ENVELOPE_MIN
MAX_OVERALL_BYTES: Final[int] = 32_768 + ENVELOPE_MIN
MAX_WRAPS: Final[int] = 200


@dataclass(frozen=True)
class KeyRow:
    sub: str
    key_version: int
    fingerprint: bytes
    enc_pub: bytes
    sig_pub: bytes


@dataclass(frozen=True)
class AssignWrap:
    key_id: str
    blob: str
    signature: bytes


@dataclass(frozen=True)
class NewAssignment:
    tenant_id: str
    conversation_id: str
    requester_sub: str
    requester_key_version: int
    reviewer_sub: str
    reviewer_key_version: int
    reviewer_fingerprint: bytes
    directory_read_at: datetime
    wraps: tuple[AssignWrap, ...]


@dataclass(frozen=True)
class NotePost:
    entry_id: str
    key_id: str
    ciphertext: bytes


@dataclass(frozen=True)
class VerificationRow:
    verification_id: str
    conversation_id: str
    status: str
    requested_by: str
    requester_key_version: int
    requested_at: datetime
    directory_read_at: datetime
    reviewer_sub: str
    reviewer_key_version: int
    reviewer_fingerprint: bytes
    started_at: datetime | None = None
    reviewed_head_seq: int | None = None
    reviewed_head: bytes | None = None
    permission_snapshot: tuple[str, ...] | None = None
    outcome: str | None = None
    overall_note: bytes | None = None
    notes_digest: bytes | None = None
    signature: bytes | None = None
    signer_key_version: int | None = None
    decided_at: datetime | None = None
    closed_at: datetime | None = None
    close_reason: str | None = None
    tsa_token: bytes | None = None

    @property
    def ref(self) -> str:
        """Names the reviewer whoever acts (§10.7 audit refs)."""
        return f"{self.verification_id}:{self.reviewer_sub}"


def _bytes(value: Any) -> bytes | None:
    return None if value is None else bytes(value)


def verification_from_row(row: Mapping[str, Any]) -> VerificationRow:
    snapshot = row["permission_snapshot"]
    return VerificationRow(
        verification_id=str(row["verification_id"]),
        conversation_id=str(row["conversation_id"]),
        status=row["status"],
        requested_by=row["requested_by"],
        requester_key_version=row["requester_key_version"],
        requested_at=row["requested_at"],
        directory_read_at=row["directory_read_at"],
        reviewer_sub=row["reviewer_sub"],
        reviewer_key_version=row["reviewer_key_version"],
        reviewer_fingerprint=bytes(row["reviewer_fingerprint"]),
        started_at=row["started_at"],
        reviewed_head_seq=row["reviewed_head_seq"],
        reviewed_head=_bytes(row["reviewed_head"]),
        permission_snapshot=None if snapshot is None else tuple(snapshot),
        outcome=row["outcome"],
        overall_note=_bytes(row["overall_note"]),
        notes_digest=_bytes(row["notes_digest"]),
        signature=_bytes(row["signature"]),
        signer_key_version=row["signer_key_version"],
        decided_at=row["decided_at"],
        closed_at=row["closed_at"],
        close_reason=row["close_reason"],
        tsa_token=_bytes(row["tsa_token"]),
    )


def new_verification_id() -> str:
    return str(uuid.uuid4())


@dataclass(frozen=True)
class AssignRequest:
    key_version: int
    reviewer_sub: str
    reviewer_key_version: int
    wraps: tuple[AssignWrap, ...]


@dataclass(frozen=True)
class Candidate:
    sub: str
    display_name: str
    languages: tuple[str, ...]
    sworn: bool
    key: KeyRow


@dataclass(frozen=True)
class InboxRow:
    verification_id: str
    status: str
    requested_at: datetime
    requested_by: str
    started_at: datetime
    ended_at: datetime | None
    messages: int
    openable: bool
    requested_by_name: str | None = None


@dataclass(frozen=True)
class DecisionPost:
    outcome: str
    overall: bytes | None
    notes: tuple[NotePost, ...]
    signature: bytes
    notes_digest: bytes
    signed_digest: bytes
    signer_key_version: int
    signer_fingerprint: bytes
    # What the signature covers; a snapshot refreshed meanwhile must not freeze beside it.
    snapshot: tuple[str, ...] = ()
    reviewed_head: bytes = b""


@dataclass(frozen=True)
class PendingDecisionStamp:
    verification_id: str
    conversation_id: str
    reviewed_head: bytes
    outcome: str
    notes_digest: bytes
    permission_snapshot: tuple[str, ...]
    signature: bytes
    url: str
    attempts: int


@dataclass(frozen=True)
class VerificationResult:
    """A record as a reader sees it: content only once decided (§10.7)."""

    row: VerificationRow
    notes: tuple[NotePost, ...] = ()
    reviewer_key: KeyRow | None = None


def summary(statuses: list[str]) -> dict[str, Any]:
    """Derived, never stored (§10.5): open records first, then the outcomes."""
    approved = statuses.count("approved")
    not_approved = statuses.count("not_approved")
    if any(status in OPEN for status in statuses):
        status = "in_review"
    elif approved or not_approved:
        status = "decided"
    else:
        status = "not_verified"
    return {"status": status, "approved": approved, "not_approved": not_approved}
