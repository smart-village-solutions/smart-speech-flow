"""A closed ceremony as browsers certify it: one generation of the recovery key's holders.

The trust route and a resharing's state both answer with these, so every
browser checks the same facts (spec §9.7, §10.6). Public values only: no
sub-share and no encrypted share leaves here, and custodians' names stay out.
"""

from __future__ import annotations

from typing import Any

from ..recording.ceremony_model import CeremonySnapshot, RecoveryKeyRecord
from ..recording.crypto.encoding import b64url


def _optional(value: bytes | None) -> str | None:
    return None if value is None else b64url(value)


def generation_body(snapshot: CeremonySnapshot) -> dict[str, Any]:
    ceremony = snapshot.ceremony
    return {
        "ceremony_id": ceremony.ceremony_id,
        "kind": ceremony.kind,
        "k": ceremony.k,
        "transcript_hash": _optional(ceremony.transcript_hash),
        "previous_transcript_hash": _optional(ceremony.previous_transcript_hash),
        "gateway_keys": [
            {"key_id": key_id, "public_key": b64url(public)}
            for key_id, public in ceremony.gateway_keys
        ],
        "participants": [
            {
                "holder_index": p.holder_index,
                "holder_ref": p.holder_ref,
                "kind": p.kind,
                "display_name": None,
                "enc_pub": b64url(p.enc_pub),
                "sig_pub": _optional(p.sig_pub),
                "fingerprint": b64url(p.fingerprint),
            }
            for p in snapshot.participants
        ],
        "dealers": list(snapshot.dealer_indices()),
        "dealings": [
            {
                "dealer_index": d.dealer_index,
                "commitments": [b64url(c) for c in d.commitments],
                "c": b64url(d.proof_c.to_bytes(32, "big")),
                "s": b64url(d.proof_s.to_bytes(32, "big")),
                "signature": _optional(d.signature),
            }
            for d in snapshot.dealings
        ],
        "transcript_signatures": [
            {"holder_index": c.holder_index, "signature": b64url(c.transcript_signature)}
            for c in snapshot.confirmations
        ],
    }


def trust_body(key: RecoveryKeyRecord, chain: list[CeremonySnapshot]) -> dict[str, Any]:
    """The key, and every generation from the one that made it to its current holders."""
    holders, holders_transcript = key.current_holders
    return {
        "recovery_key": {
            "key_id": key.key_id,
            "transcript_hash": b64url(key.transcript_hash),
            "holders_ceremony_id": holders,
            "holders_transcript_hash": b64url(holders_transcript),
        },
        "generations": [generation_body(snapshot) for snapshot in chain],
    }
