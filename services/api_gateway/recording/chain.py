"""The signed chain of a recorded conversation (spec §11.1, Appendix A.6).

Each stored message, failed message, consent and playback is one entry. An
entry's hash covers its fields and the previous entry's hash, and the gateway
signs that hash, so removing, reordering or altering an entry breaks every
hash after it. The objects an entry lists are named by key, size and
ciphertext hash; the version ID the store assigns on upload is recorded
beside the entry, not in it, because it exists only once the spool has
delivered the object, which may be long after later entries were decided.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

from cryptography.hazmat.primitives.asymmetric import ec

from .crypto import tags
from .crypto.encoding import Field
from .crypto.signatures import sign_fields, signed_digest, verify_fields

GENESIS: Final[bytes] = bytes(32)

EntryKind = Literal["message", "failed", "consent", "playback", "amendment"]


@dataclass(frozen=True)
class ChainObject:
    object_type: str
    key: str
    size: int
    sha256: str  # hex, of the ciphertext as stored


def objects_json(objects: Sequence[ChainObject]) -> str:
    """The canonical text the signature covers: sorted by type, compact, sorted keys."""
    return json.dumps(
        [
            {"key": item.key, "sha256": item.sha256, "size": item.size, "type": item.object_type}
            for item in sorted(objects, key=lambda item: item.object_type)
        ],
        separators=(",", ":"),
        sort_keys=True,
    )


def object_types(objects_text: str) -> frozenset[str]:
    return frozenset(item["type"] for item in json.loads(objects_text))


@dataclass(frozen=True)
class ChainEntry:
    tenant_id: str
    conversation_id: str
    seq: int
    entry_id: str
    kind: EntryKind
    window_id: str | None
    key_id: str
    objects: str  # objects_json(...), kept verbatim
    prev_hash: bytes
    hash: bytes
    signer_key_id: str
    signature: bytes
    created_at: datetime


def _fields(
    tenant_id: str,
    conversation_id: str,
    seq: int,
    kind: str,
    window_id: str | None,
    key_id: str,
    objects: str,
    prev_hash: bytes,
) -> tuple[Field, ...]:
    # An entry outside a window (a playback after a stop) signs an empty window.
    return (tenant_id, conversation_id, seq, kind, window_id or "", key_id, objects, prev_hash)


def seal_entry(
    *,
    tenant_id: str,
    conversation_id: str,
    seq: int,
    entry_id: str,
    kind: EntryKind,
    window_id: str | None,
    key_id: str,
    objects: Sequence[ChainObject],
    prev_hash: bytes,
    created_at: datetime,
    signing_key: ec.EllipticCurvePrivateKey,
    signer_key_id: str,
) -> ChainEntry:
    text = objects_json(objects)
    fields = _fields(tenant_id, conversation_id, seq, kind, window_id, key_id, text, prev_hash)
    return ChainEntry(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        seq=seq,
        entry_id=entry_id,
        kind=kind,
        window_id=window_id,
        key_id=key_id,
        objects=text,
        prev_hash=prev_hash,
        hash=signed_digest(tags.CHAIN_SIG, *fields),
        signer_key_id=signer_key_id,
        signature=sign_fields(signing_key, tags.CHAIN_SIG, *fields),
        created_at=created_at,
    )


def entry_is_authentic(entry: ChainEntry, signer_public_key: bytes) -> bool:
    fields = _fields(
        entry.tenant_id,
        entry.conversation_id,
        entry.seq,
        entry.kind,
        entry.window_id,
        entry.key_id,
        entry.objects,
        entry.prev_hash,
    )
    return signed_digest(tags.CHAIN_SIG, *fields) == entry.hash and verify_fields(
        signer_public_key, entry.signature, tags.CHAIN_SIG, *fields
    )


def chain_is_intact(entries: Sequence[ChainEntry], gateway_keys: Mapping[str, bytes]) -> bool:
    """One conversation's entries in `seq` order, starting at 1, each signed by a known key."""
    previous = GENESIS
    for expected_seq, entry in enumerate(entries, start=1):
        if entry.seq != expected_seq or entry.prev_hash != previous:
            return False
        signer = gateway_keys.get(entry.signer_key_id)
        if signer is None or not entry_is_authentic(entry, signer):
            return False
        previous = entry.hash
    return True
