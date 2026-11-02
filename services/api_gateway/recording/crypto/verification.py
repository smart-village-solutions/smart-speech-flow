"""Byte layouts of a verification record (spec Appendix A.3a).

The browser builds the same values (core/crypto/verification.ts); the shared
vectors pin both.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from typing import Final, Literal

from . import tags
from .encoding import Field, enc

OUTCOMES: Final[frozenset[str]] = frozenset({"approved", "not_approved"})
NotePart = Literal["note", "overall"]


def note_aad(
    tenant_id: str,
    conversation_id: str,
    verification_id: str,
    part: NotePart,
    entry_id: str,
    key_id: str,
) -> bytes:
    if part not in ("note", "overall"):
        raise ValueError("a note part is 'note' or 'overall'")
    return enc(
        tags.VERIFICATION_NOTE, tenant_id, conversation_id, verification_id, part, entry_id, key_id
    )


def _code_points(value: str) -> list[int]:
    return [ord(character) for character in value]


def notes_digest(overall: bytes | None, notes: Iterable[tuple[str, str, bytes]]) -> bytes:
    """`notes` holds (entry_id, key_id, ciphertext); each ciphertext is hashed, never encoded."""
    ordered = sorted(notes, key=lambda note: _code_points(note[0]))
    fields: list[Field] = [b"" if overall is None else hashlib.sha256(overall).digest()]
    fields.append(len(ordered))
    for entry_id, key_id, ciphertext in ordered:
        fields += [entry_id, key_id, hashlib.sha256(ciphertext).digest()]
    return hashlib.sha256(enc(*fields)).digest()


def verification_fields(
    tenant_id: str,
    verification_id: str,
    conversation_id: str,
    reviewed_head: bytes,
    outcome: str,
    digest: bytes,
    snapshot: Sequence[str],
) -> tuple[Field, ...]:
    if outcome not in OUTCOMES:
        raise ValueError("an outcome is 'approved' or 'not_approved'")
    members = sorted(snapshot, key=_code_points)
    return (
        tenant_id,
        verification_id,
        conversation_id,
        reviewed_head,
        outcome,
        digest,
        len(members),
        *members,
    )


def decision_imprint(signed_digest: bytes, signature: bytes) -> bytes:
    return hashlib.sha256(signed_digest + signature).digest()
