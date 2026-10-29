"""Records and views of exceptional access (spec §9.5).

The repository returns `Refused` instead of raising where the refusal itself
must be committed (an expiry, an audit of a self-approval), so the service
turns it into an error after the transaction has ended.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

REQUEST_LIFETIME: Final[timedelta] = timedelta(days=7)
MAX_CONVERSATIONS: Final[int] = 50
# What one approval or one wrap post may carry; a larger scope could never complete.
MAX_SCOPE_KEYS: Final[int] = 500
SYSTEM_ACTOR: Final[str] = "system"
REJECTION_FAULTS: Final[frozenset[str]] = frozenset({"partial_unreadable", "proof_invalid"})
INTEGRITY_STAGES: Final[frozenset[str]] = frozenset(
    {"trust", "wrap_signature", "approval_signature", "partial_hash", "wrap_damaged"}
)


@dataclass(frozen=True)
class Refused:
    """A refusal code the service maps to an answer; its audit is already committed."""

    code: str


@dataclass(frozen=True)
class ScopeKey:
    conversation_id: str
    key_id: str


@dataclass(frozen=True)
class Candidate:
    conversation_id: str
    started_at: datetime
    ended_at: datetime
    retention_until: datetime
    legal_hold: bool
    incomplete: bool
    key_ids: tuple[str, ...]


@dataclass(frozen=True)
class NewRequest:
    tenant_id: str
    request_id: str
    requester_sub: str
    requester_key_version: int
    recovery_key_id: str
    reason: str
    conversation_ids: tuple[str, ...]
    signature: bytes
    created_at: datetime


@dataclass(frozen=True)
class RequestRow:
    request_id: str
    kind: str
    requester_sub: str
    requester_key_version: int
    recovery_key_id: str
    reason: str
    request_signature: bytes
    status: str
    created_at: datetime
    expires_at: datetime
    closed_at: datetime | None


@dataclass(frozen=True)
class DecisionRow:
    holder_index: int
    attempt: int
    custodian_sub: str
    decision: str
    reason: str | None
    signed_partials: tuple[tuple[str, bytes], ...]
    approval_signature: bytes | None
    decided_at: datetime
    rejected: bool


@dataclass(frozen=True)
class ApproverScopeKey:
    conversation_id: str
    key_id: str
    employee_sub: str
    started_at: datetime
    ended_at: datetime
    recovery_blob: str  # the service serves only its R
    creator_ref: str
    creator_signature: bytes


@dataclass(frozen=True)
class ApprovalContext:
    """What a custodian needs to approve; never a wrap's nonce or ct once it leaves the service."""

    request: RequestRow
    requester_enc_pub: bytes
    requester_sig_pub: bytes
    signed_scope: tuple[ScopeKey, ...]
    remaining: tuple[ApproverScopeKey, ...]
    holder_index: int
    attempt: int
    encrypted_share: str


@dataclass(frozen=True)
class Progress:
    request: RequestRow
    k: int
    decisions: tuple[DecisionRow, ...]
    remaining: tuple[ScopeKey, ...]
    # Every conversation the request named, as the list counts them, open or closed.
    conversations: int


@dataclass(frozen=True)
class ServedWrap:
    conversation_id: str
    key_id: str
    blob: str
    creator_ref: str
    creator_signature: bytes


@dataclass(frozen=True)
class ServedApproval:
    holder_index: int
    attempt: int
    signed_partials: tuple[tuple[str, bytes], ...]
    approval_signature: bytes
    blobs: Mapping[str, str]


@dataclass(frozen=True)
class ServedPartials:
    wraps: tuple[ServedWrap, ...]
    approvals: tuple[ServedApproval, ...]


@dataclass(frozen=True)
class NewWrap:
    conversation_id: str
    key_id: str
    blob: str
    signature: bytes


@dataclass(frozen=True)
class Approval:
    """A custodian's submission; `verify` checks the approval signature for a holder index."""

    partials: Mapping[str, str]  # key ID -> sealed partial JSON
    signature: bytes


ScopeVerifier = Callable[[tuple[ScopeKey, ...]], bool]
ApprovalVerifier = Callable[[int, int, bytes], bool]  # holder index, attempt, custodian sig_pub
WrapVerifier = Callable[[NewWrap], bool]
