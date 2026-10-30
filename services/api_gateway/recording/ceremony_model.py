"""The recovery-key ceremony's records and the public checks on them (spec §9.2, A.8).

Everything here works on public values only: commitments, proofs, public
shares and signatures. The checks repeat, on the gateway, what every
custodian's browser verifies, so a malformed dealing is refused at the door
rather than discovered by each holder.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from .audit import AuditEvent
from .crypto import tags
from .crypto.curve import InvalidPoint, decode_point
from .crypto.ecies import Sealed, SealedPayloadError
from .crypto.proofs import holder_public_share, recovery_public_key, verify_schnorr
from .crypto.signatures import dealing_fields, verify_fields
from .crypto.transcript import Dealing, Participant, TranscriptInput, transcript_hash

MAX_K: Final[int] = 5
MAX_CUSTODIANS: Final[int] = 10
CEREMONY_LIFETIME: Final[timedelta] = timedelta(hours=24)
MAX_SEALED_CHARACTERS: Final[int] = 1024
CUSTODIAN: Final[str] = "custodian"
PAPER: Final[str] = "paper"
GENERATION: Final[str] = "generation"
RESHARING: Final[str] = "resharing"
# Reasons a participant may give; "expired" is the gateway's own.
ABORT_REASONS: Final[frozenset[str]] = frozenset(
    {
        "cancelled",
        "fingerprint_mismatch",
        "proof_invalid",
        "signature_invalid",
        "subshare_invalid",
        "transcript_mismatch",
        "device_lost",
        "contribution_invalid",
        "chain_invalid",
    }
)


class CeremonyError(Exception):
    """A refused ceremony action, carrying the HTTP status and code the route answers with."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def invalid(code: str, message: str) -> CeremonyError:
    return CeremonyError(422, code, message)


def conflict(code: str, message: str) -> CeremonyError:
    return CeremonyError(409, code, message)


@dataclass(frozen=True)
class CeremonyParticipant:
    holder_index: int
    holder_ref: str
    kind: str
    display_name: str | None
    enc_pub: bytes
    # None for a paper holder: the ceremony device deals nothing and signs nothing.
    sig_pub: bytes | None
    fingerprint: bytes


@dataclass(frozen=True)
class CeremonyDealer:
    """Who deals: a first ceremony's custodian, or an old holder by its old index (§9.7)."""

    dealer_index: int
    holder_ref: str
    kind: str


@dataclass(frozen=True)
class DealingRecord:
    dealer_index: int
    commitments: tuple[bytes, ...]
    proof_c: int
    proof_s: int
    # None only for a paper sheet dealing in a resharing: the device has no signing key.
    signature: bytes | None
    dealt_at: datetime
    # Recipient index -> sealed sub-share. Empty when read for a ceremony view.
    subshares: Mapping[int, str]


@dataclass(frozen=True)
class ConfirmationRecord:
    holder_index: int
    transcript_signature: bytes
    encrypted_share: str
    confirmed_at: datetime
    # A resharing's custodian proves it holds the share it sealed (§9.7).
    share_proof: tuple[int, int] | None = None


@dataclass(frozen=True)
class CeremonyRecord:
    tenant_id: str
    ceremony_id: str
    k: int
    started_by: str
    started_at: datetime
    expires_at: datetime
    status: str
    gateway_keys: tuple[tuple[str, bytes], ...]
    transcript_hash: bytes | None = None
    paper_confirmed_at: datetime | None = None
    kind: str = GENERATION
    recovery_key_id: str | None = None
    previous_transcript_hash: bytes | None = None


@dataclass(frozen=True)
class FailedCeremony:
    """The tenant's latest ceremony, when it ended without a key; every participant is told why."""

    ceremony_id: str
    reason: str  # an ABORT_REASONS value, or "expired"
    ended_at: datetime


@dataclass(frozen=True)
class CeremonySnapshot:
    ceremony: CeremonyRecord
    participants: tuple[CeremonyParticipant, ...]
    dealings: tuple[DealingRecord, ...]
    confirmations: tuple[ConfirmationRecord, ...]
    # Empty for a snapshot built before the dealers were read: the custodians deal then.
    dealers: tuple[CeremonyDealer, ...] = ()

    @property
    def custodians(self) -> tuple[CeremonyParticipant, ...]:
        return tuple(p for p in self.participants if p.kind == CUSTODIAN)

    @property
    def paper_holders(self) -> tuple[CeremonyParticipant, ...]:
        return tuple(p for p in self.participants if p.kind == PAPER)

    def participant(self, index: int) -> CeremonyParticipant:
        return next(p for p in self.participants if p.holder_index == index)

    def custodian(self, user_sub: str) -> CeremonyParticipant | None:
        return next((p for p in self.custodians if p.holder_ref == user_sub), None)

    def has_dealt(self, holder_index: int) -> bool:
        return any(d.dealer_index == holder_index for d in self.dealings)

    def has_confirmed(self, holder_index: int) -> bool:
        return any(c.holder_index == holder_index for c in self.confirmations)

    def dealer_indices(self) -> tuple[int, ...]:
        if self.dealers:
            return tuple(d.dealer_index for d in self.dealers)
        return tuple(p.holder_index for p in self.custodians)

    def dealer(self, index: int) -> CeremonyDealer | None:
        return next((d for d in self.dealers if d.dealer_index == index), None)

    def custodian_dealer(self, user_sub: str) -> CeremonyDealer | None:
        return next(
            (d for d in self.dealers if d.kind == CUSTODIAN and d.holder_ref == user_sub), None
        )

    def all_dealt(self) -> bool:
        return all(self.has_dealt(index) for index in self.dealer_indices())

    def ready_to_activate(self) -> bool:
        confirmed = all(self.has_confirmed(p.holder_index) for p in self.custodians)
        paper_done = not self.paper_holders or self.ceremony.paper_confirmed_at is not None
        return self.ceremony.status == "confirming" and confirmed and paper_done


@dataclass(frozen=True)
class RecoveryKeyRecord:
    tenant_id: str
    key_id: str
    recovery_public_key: bytes
    k: int
    n: int
    mode: str
    transcript_hash: bytes
    canary_wrap: str
    canary_signature: bytes
    canary_signer_key_id: str
    activated_at: datetime
    # The current holders' ceremony and transcript; None until read for a key (§9.7).
    holders_ceremony_id: str | None = None
    holders_transcript_hash: bytes | None = None

    @property
    def current_holders(self) -> tuple[str, bytes]:
        """The ceremony and transcript of the key's current generation."""
        return (
            self.holders_ceremony_id or self.key_id,
            self.holders_transcript_hash or self.transcript_hash,
        )


@dataclass(frozen=True)
class RecoveryShareRecord:
    holder_index: int
    holder_ref: str
    holder_public_share: bytes
    # None for a paper share, which exists only on paper.
    encrypted_share: str | None


# Builds the key, its shares and the audit event from a ceremony ready to activate.
# The store calls it inside the transaction that records the last signature.
Activation = Callable[
    [CeremonySnapshot], tuple[RecoveryKeyRecord, Sequence[RecoveryShareRecord], AuditEvent]
]


@dataclass(frozen=True)
class DealingSubmission:
    commitments: tuple[bytes, ...]
    proof_c: int
    proof_s: int
    signature: bytes | None
    subshares: Mapping[int, str]


def mode_of(k: int) -> str:
    """One share opens alone in standard mode; enhanced needs several (spec §9.1)."""
    return "standard" if k == 1 else "enhanced"


def dealing_record(index: int, dealing: DealingSubmission, now: datetime) -> DealingRecord:
    return DealingRecord(
        index,
        dealing.commitments,
        dealing.proof_c,
        dealing.proof_s,
        dealing.signature,
        now,
        dealing.subshares,
    )


def transcript_input(snapshot: CeremonySnapshot) -> TranscriptInput:
    """The transcript of a fully dealt ceremony, with X and every X_i computed here."""
    dealings = sorted(snapshot.dealings, key=lambda dealing: dealing.dealer_index)
    commitment_lists = [dealing.commitments for dealing in dealings]
    ceremony = snapshot.ceremony
    return TranscriptInput(
        tenant_id=ceremony.tenant_id,
        ceremony_id=ceremony.ceremony_id,
        k=ceremony.k,
        participants=tuple(
            Participant(p.holder_ref, p.holder_index, p.fingerprint) for p in snapshot.participants
        ),
        dealings=tuple(
            Dealing(d.dealer_index, d.commitments, d.proof_c, d.proof_s) for d in dealings
        ),
        recovery_public_key=recovery_public_key(commitment_lists),
        holder_shares=tuple(
            holder_public_share(p.holder_index, commitment_lists)
            for p in sorted(snapshot.participants, key=lambda item: item.holder_index)
        ),
        gateway_keys=ceremony.gateway_keys,
        previous_transcript=ceremony.previous_transcript_hash or b"",
    )


def computed_transcript_hash(snapshot: CeremonySnapshot) -> bytes:
    return transcript_hash(transcript_input(snapshot))


def check_sealed(text: str, expected_type: str) -> None:
    """Shape only: the gateway cannot open a payload sealed for someone else."""
    if len(text) > MAX_SEALED_CHARACTERS:
        raise invalid("INVALID_PAYLOAD", "A sealed payload is too large")
    try:
        Sealed.from_json(text, expected_type=expected_type)
    except (SealedPayloadError, InvalidPoint):
        raise invalid("INVALID_PAYLOAD", "A sealed payload is malformed") from None


def check_commitments(commitments: tuple[bytes, ...], k: int) -> None:
    if len(commitments) != k:
        raise invalid("INVALID_DEALING", "A dealing has one commitment per coefficient")
    try:
        for commitment in commitments:
            decode_point(commitment)
    except InvalidPoint:
        raise invalid("INVALID_DEALING", "A commitment is not a P-256 point") from None


def check_dealing(
    snapshot: CeremonySnapshot, dealer: CeremonyParticipant, dealing: DealingSubmission
) -> None:
    """Every public part of a dealing, as each holder's browser will check it again."""
    ceremony = snapshot.ceremony
    check_commitments(dealing.commitments, ceremony.k)
    if not verify_schnorr(
        ceremony.tenant_id,
        ceremony.ceremony_id,
        dealer.holder_index,
        dealing.commitments[0],
        dealing.proof_c,
        dealing.proof_s,
    ):
        raise invalid("INVALID_DEALING", "The proof of knowledge does not verify")
    signed = dealing_fields(
        ceremony.tenant_id,
        ceremony.ceremony_id,
        dealer.holder_index,
        dealing.commitments,
        dealing.proof_c,
        dealing.proof_s,
    )
    signer, signature = dealer.sig_pub, dealing.signature
    if signer is None or signature is None:
        raise invalid("INVALID_DEALING", "A custodian's dealing is signed")
    if not verify_fields(signer, signature, tags.DEALING_SIG, *signed):
        raise invalid("INVALID_DEALING", "The dealer's signature does not verify")
    check_subshares(snapshot, dealing)


def check_subshares(snapshot: CeremonySnapshot, dealing: DealingSubmission) -> None:
    if set(dealing.subshares) != {p.holder_index for p in snapshot.participants}:
        raise invalid("INVALID_DEALING", "A dealing has one sub-share per holder")
    for sealed in dealing.subshares.values():
        check_sealed(sealed, tags.SUBSHARE)
