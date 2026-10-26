"""Key fingerprints (A.9) and the ceremony transcript hash (A.8)."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from . import tags
from .encoding import Field, enc, scalar_to_bytes

DISPLAY_BYTES: Final[int] = 20
PAPER_DEVICE_REF: Final[str] = "paper-device"


def fingerprint(tenant_id: str, user_sub: str, enc_pub: bytes, sig_pub: bytes) -> bytes:
    return hashlib.sha256(enc(tags.FINGERPRINT, tenant_id, user_sub, enc_pub, sig_pub)).digest()


def paper_device_fingerprint(tenant_id: str, device_pub: bytes) -> bytes:
    """The ceremony device has an encryption key only; it stands in for both halves."""
    return fingerprint(tenant_id, PAPER_DEVICE_REF, device_pub, device_pub)


def display_fingerprint(raw: bytes) -> str:
    """First 20 bytes, hex, in groups of four: `a1b2 c3d4 ...`."""
    text = raw[:DISPLAY_BYTES].hex()
    return " ".join(text[start : start + 4] for start in range(0, len(text), 4))


@dataclass(frozen=True)
class Participant:
    holder_ref: str
    index: int
    fingerprint: bytes


@dataclass(frozen=True)
class Dealing:
    dealer_index: int
    commitments: tuple[bytes, ...]
    proof_c: int
    proof_s: int


@dataclass(frozen=True)
class TranscriptInput:
    tenant_id: str
    ceremony_id: str
    k: int
    participants: tuple[Participant, ...]
    dealings: tuple[Dealing, ...]
    recovery_public_key: bytes
    holder_shares: tuple[bytes, ...]
    gateway_keys: tuple[tuple[str, bytes], ...]
    previous_transcript: bytes = b""


def transcript_fields(data: TranscriptInput) -> tuple[Field, ...]:
    """Every list in a fixed order: participants and dealings by index, keys by ID."""
    fields: list[Field] = [data.tenant_id, data.ceremony_id, data.k, len(data.participants)]
    for participant in sorted(data.participants, key=lambda item: item.index):
        fields += [participant.holder_ref, participant.index, participant.fingerprint]
    for dealing in sorted(data.dealings, key=lambda item: item.dealer_index):
        fields += [dealing.dealer_index, *dealing.commitments]
        fields += [scalar_to_bytes(dealing.proof_c), scalar_to_bytes(dealing.proof_s)]
    fields += [data.recovery_public_key, *data.holder_shares]
    for key_id, public_key in sorted(data.gateway_keys):
        fields += [key_id, public_key]
    fields.append(data.previous_transcript)
    return tuple(fields)


def transcript_hash(data: TranscriptInput) -> bytes:
    return hashlib.sha256(enc(tags.TRANSCRIPT, *transcript_fields(data))).digest()


def holder_shares_in_order(shares: Sequence[tuple[int, bytes]]) -> tuple[bytes, ...]:
    return tuple(share for _, share in sorted(shares))
