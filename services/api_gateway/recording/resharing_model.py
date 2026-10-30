"""A resharing's records and the public checks on them (spec §9.7).

k holders of the current generation each deal `λ_i·x_i` to a new holder set.
Everything here works on public values: the gateway re-checks what the
dealers publish, as every new holder's browser does again, and confirms at
activation that the new public shares still interpolate to X.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .ceremony_model import (
    CUSTODIAN,
    MAX_CUSTODIANS,
    MAX_K,
    PAPER,
    CeremonyDealer,
    CeremonyParticipant,
    CeremonySnapshot,
    DealingSubmission,
    check_commitments,
    check_subshares,
    invalid,
)
from .crypto import tags
from .crypto.curve import InvalidPoint, add, decode_point, encode_point, multiply
from .crypto.proofs import holder_public_share, lagrange_at_zero, verify_schnorr, verify_share_proof
from .crypto.signatures import participants_digest, reshare_dealing_fields, verify_fields


@dataclass(frozen=True)
class HolderGeneration:
    """The key's current holders: who they are, their threshold, and X_i per index."""

    ceremony_id: str
    k: int
    transcript_hash: bytes
    participants: tuple[CeremonyParticipant, ...]
    public_shares: Mapping[int, bytes]

    def holder(self, index: int) -> CeremonyParticipant | None:
        return next((p for p in self.participants if p.holder_index == index), None)


@dataclass(frozen=True)
class ResharingStart:
    k: int
    custodians: tuple[str, ...]
    # Old holder indices of the current generation; exactly its k.
    dealers: tuple[int, ...]
    # The ceremony device's key; present exactly when a new paper backup is wanted.
    paper_device_pub: bytes | None
    # The generation the admin chose dealers from: indices mean other holders in another.
    holders_ceremony_id: str


def _check_new_set(start: ResharingStart) -> None:
    if not 1 <= start.k <= MAX_K:
        raise invalid("INVALID_CEREMONY", f"k must be between 1 and {MAX_K}")
    if len(set(start.custodians)) != len(start.custodians):
        raise invalid("INVALID_CEREMONY", "Each custodian is named once")
    if not start.k + 1 <= len(start.custodians) <= MAX_CUSTODIANS:
        raise invalid("INVALID_CEREMONY", f"Name between k+1 and {MAX_CUSTODIANS} custodians")


def _check_dealers(
    start: ResharingStart, current: HolderGeneration, usable: Mapping[str, bool]
) -> None:
    holders = [current.holder(index) for index in set(start.dealers)]
    if len(holders) != len(start.dealers) or len(holders) != current.k or None in holders:
        raise invalid("INVALID_DEALERS", "Name exactly k distinct current holders as dealers")
    for holder in holders:
        if holder is not None and holder.kind == CUSTODIAN and not usable.get(holder.holder_ref):
            raise invalid("DEALER_UNUSABLE", "A dealer's share can no longer be opened")


def _check_device(start: ResharingStart, starter: str, current: HolderGeneration) -> None:
    sheets_deal = any(
        holder is not None and holder.kind == PAPER
        for holder in (current.holder(index) for index in start.dealers)
    )
    if not sheets_deal and start.paper_device_pub is None:
        return
    old = {p.holder_ref for p in current.participants if p.kind == CUSTODIAN}
    if starter in old or starter in start.custodians:
        raise invalid("INVALID_CEREMONY", "The ceremony device may not belong to a custodian")
    if start.paper_device_pub is None:
        return
    try:
        decode_point(start.paper_device_pub)
    except InvalidPoint:
        raise invalid("INVALID_CEREMONY", "The device key is not a P-256 point") from None


def validate_start(
    start: ResharingStart, starter: str, current: HolderGeneration, usable: Mapping[str, bool]
) -> None:
    """The refusals of §9.7 that need no directory; `usable` maps custodian refs to openable."""
    _check_new_set(start)
    _check_dealers(start, current, usable)
    _check_device(start, starter, current)


def dealers_of(start: ResharingStart, current: HolderGeneration) -> tuple[CeremonyDealer, ...]:
    """Under their old indices, which the new holders' indices may repeat (§9.7)."""
    dealers = []
    for index in sorted(start.dealers):
        holder = current.holder(index)
        if holder is not None:
            dealers.append(CeremonyDealer(index, holder.holder_ref, holder.kind))
    return tuple(dealers)


def contribution(dealer_index: int, dealers: Sequence[int], public_share: bytes) -> bytes:
    """λ_i·X_i: what the dealer's C_i0 must be, so that Σ C_i0 is X."""
    weight = lagrange_at_zero(dealer_index, dealers)
    point = multiply(weight, decode_point(public_share))
    if point is None:
        raise InvalidPoint("a contribution is the identity")
    return encode_point(point)


def holders_digest(snapshot: CeremonySnapshot) -> bytes:
    return participants_digest(
        [(p.holder_index, p.holder_ref, p.fingerprint) for p in snapshot.participants]
    )


def _check_signature(
    snapshot: CeremonySnapshot,
    dealer: CeremonyDealer,
    current: HolderGeneration,
    dealing: DealingSubmission,
) -> None:
    if dealer.kind == PAPER:
        if dealing.signature is not None:
            raise invalid("INVALID_DEALING", "A paper sheet signs nothing")
        return
    holder = current.holder(dealer.dealer_index)
    signer = None if holder is None else holder.sig_pub
    if signer is None or dealing.signature is None:
        raise invalid("INVALID_DEALING", "A custodian's dealing is signed")
    ceremony = snapshot.ceremony
    signed = reshare_dealing_fields(
        ceremony.tenant_id,
        ceremony.ceremony_id,
        dealer.dealer_index,
        dealing.commitments,
        dealing.proof_c,
        dealing.proof_s,
        ceremony.previous_transcript_hash or b"",
        holders_digest(snapshot),
    )
    if not verify_fields(signer, dealing.signature, tags.RESHARE_DEALING_SIG, *signed):
        raise invalid("INVALID_DEALING", "The dealer's signature does not verify")


def check_resharing_dealing(
    snapshot: CeremonySnapshot,
    dealer: CeremonyDealer,
    current: HolderGeneration,
    dealing: DealingSubmission,
) -> None:
    """§9.2's checks, plus C_i0 == λ_i·X_i and the dealer's consent to the new set."""
    ceremony = snapshot.ceremony
    check_commitments(dealing.commitments, ceremony.k)
    if not verify_schnorr(
        ceremony.tenant_id,
        ceremony.ceremony_id,
        dealer.dealer_index,
        dealing.commitments[0],
        dealing.proof_c,
        dealing.proof_s,
    ):
        raise invalid("INVALID_DEALING", "The proof of knowledge does not verify")
    expected = contribution(
        dealer.dealer_index,
        snapshot.dealer_indices(),
        current.public_shares[dealer.dealer_index],
    )
    if dealing.commitments[0] != expected:
        raise invalid("INVALID_DEALING", "The contribution is not this dealer's share")
    _check_signature(snapshot, dealer, current, dealing)
    check_subshares(snapshot, dealing)


def new_public_shares(snapshot: CeremonySnapshot) -> dict[int, bytes]:
    """X'_j for every new holder, from the dealers' commitments."""
    lists = [d.commitments for d in sorted(snapshot.dealings, key=lambda d: d.dealer_index)]
    return {
        p.holder_index: holder_public_share(p.holder_index, lists) for p in snapshot.participants
    }


def end_to_end_holds(snapshot: CeremonySnapshot, recovery_public_key: bytes) -> bool:
    """Σ λ'_j·X'_j over the k' custodians of lowest index is X: the new shares rebuild x."""
    shares = new_public_shares(snapshot)
    chosen = sorted(p.holder_index for p in snapshot.custodians)[: snapshot.ceremony.k]
    total = None
    for index in chosen:
        total = add(total, multiply(lagrange_at_zero(index, chosen), decode_point(shares[index])))
    return total is not None and encode_point(total) == recovery_public_key


def check_share_proof(
    snapshot: CeremonySnapshot, holder_index: int, proof: tuple[int, int] | None
) -> None:
    if proof is None:
        raise invalid("INVALID_CONFIRMATION", "A resharing's custodian proves its share")
    ceremony = snapshot.ceremony
    public = new_public_shares(snapshot)[holder_index]
    if not verify_share_proof(
        ceremony.tenant_id, ceremony.ceremony_id, holder_index, public, *proof
    ):
        raise invalid("INVALID_CONFIRMATION", "The share proof does not verify")
