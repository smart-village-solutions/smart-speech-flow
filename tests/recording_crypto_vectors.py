"""Builds tests/fixtures/recording/crypto_vectors_v1.json.

Every random value is derived from a label, so the file is reproducible:
test_recording_crypto_vectors.py regenerates it and compares. The browser's
suite (services/frontend/src/core/crypto/__tests__/vectors.test.ts) computes
the same outputs from the same inputs.

    PYTHONPATH=. python -m tests.recording_crypto_vectors
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.api_gateway.recording.chain import GENESIS, ChainObject, seal_entry
from services.api_gateway.recording.crypto import aead, ecies, signatures, tags
from services.api_gateway.recording.crypto.curve import ORDER, decode_point
from services.api_gateway.recording.crypto.encoding import Field, b64url, enc, from_b64url
from services.api_gateway.recording.crypto.proofs import (
    holder_public_share,
    recovery_public_key,
)
from services.api_gateway.recording.crypto.transcript import (
    Dealing,
    Participant,
    TranscriptInput,
    display_fingerprint,
    fingerprint,
    paper_device_fingerprint,
    transcript_hash,
)
from services.api_gateway.recording.secrets import gateway_key_id
from services.api_gateway.recording.storage.archive import object_key
from services.api_gateway.recording.timestamps import _integer, _tlv
from tests import recording_crypto_reference as ref

FIXTURE = Path(__file__).parent / "fixtures" / "recording" / "crypto_vectors_v1.json"
TENANT = "tenant-kassel"
CONVERSATION = "6f1c1d2e-3a4b-4c5d-8e9f-0a1b2c3d4e5f"
KEY_ID = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"
CEREMONY = "0d6c2b1a-9e8f-4d7c-b6a5-4f3e2d1c0b9a"
REQUEST = "5b4a3c2d-1e0f-4a9b-8c7d-6e5f4a3b2c1d"
WINDOW = "2c3d4e5f-6a7b-4c8d-9e0f-1a2b3c4d5e6f"
_CHAIN_KINDS = (
    ("consent", "consent.json"),
    ("message", "record.json"),
    ("amendment", "amendment.json"),
)


def scalar(label: str) -> int:
    return int.from_bytes(hashlib.sha256(label.encode()).digest(), "big") % ORDER


def label_bytes(label: str, length: int) -> bytes:
    return hashlib.sha256(label.encode()).digest()[:length]


def hex32(value: int) -> str:
    return value.to_bytes(32, "big").hex()


def typed(field: Field) -> dict[str, Any]:
    if isinstance(field, bytes):
        return {"b": b64url(field)}
    if isinstance(field, str):
        return {"s": field}
    return {"i": field}


def encoding_vectors() -> list[dict[str, Any]]:
    cases: list[tuple[Field, ...]] = [
        (),
        ("",),
        ("ssf-rec/object/v1", "Grüße", 0, 4294967296),
        (b"\x00\x01\xff", "a", 12),
    ]
    return [{"fields": [typed(f) for f in case], "hex": enc(*case).hex()} for case in cases]


def fingerprint_vector() -> dict[str, Any]:
    enc_pub, sig_pub = ref.public_point(scalar("alice-enc")), ref.public_point(scalar("alice-sig"))
    raw = fingerprint(TENANT, "alice", enc_pub, sig_pub)
    return {
        "tenant_id": TENANT,
        "user_sub": "alice",
        "enc_pub": b64url(enc_pub),
        "sig_pub": b64url(sig_pub),
        "fingerprint": b64url(raw),
        "display": display_fingerprint(raw),
        "paper_device": {
            "device_pub": b64url(enc_pub),
            "fingerprint": b64url(paper_device_fingerprint(TENANT, enc_pub)),
        },
    }


def envelope_vectors() -> dict[str, Any]:
    key, nonce = label_bytes("object-key", 32), label_bytes("object-nonce", 12)
    entry = "1c2d3e4f-5a6b-4c7d-8e9f-a0b1c2d3e4f5"
    plaintext = b"RIFF....WAVEfmt "
    object_aad = aead.object_aad(TENANT, CONVERSATION, entry, "original.wav", KEY_ID)
    layer_key, layer_nonce = label_bytes("layer-key", 32), label_bytes("layer-nonce", 12)
    layer_plain = b'{"v":1}'
    return {
        "object": {
            "key": b64url(key),
            "nonce": b64url(nonce),
            "tenant_id": TENANT,
            "conversation_id": CONVERSATION,
            "entry_id": entry,
            "object_type": "original.wav",
            "key_id": KEY_ID,
            "plaintext": b64url(plaintext),
            "envelope": b64url(aead.seal(key, plaintext, object_aad, nonce=nonce)),
        },
        "server_layer": {
            "key": b64url(layer_key),
            "nonce": b64url(layer_nonce),
            "tenant_id": TENANT,
            "user_sub": "alice",
            "plaintext": b64url(layer_plain),
            "envelope": b64url(
                aead.seal(
                    layer_key,
                    layer_plain,
                    aead.server_layer_aad(TENANT, "alice"),
                    nonce=layer_nonce,
                )
            ),
        },
    }


def sealed_vector(type_tag: str, context: tuple[Field, ...], plaintext: bytes) -> dict[str, Any]:
    recipient_scalar = scalar(f"{type_tag}-recipient")
    ephemeral_scalar = scalar(f"{type_tag}-ephemeral")
    nonce = label_bytes(f"{type_tag}-nonce", 12)
    sealed = ecies.seal(
        type_tag,
        ref.public_point(recipient_scalar),
        plaintext,
        context,
        ephemeral_key=ref.private_key(ephemeral_scalar),
        nonce=nonce,
    )
    return {
        "type": type_tag,
        "recipient_scalar": hex32(recipient_scalar),
        "recipient": b64url(ref.public_point(recipient_scalar)),
        "ephemeral_scalar": hex32(ephemeral_scalar),
        "nonce": b64url(nonce),
        "context": [typed(f) for f in context],
        "plaintext": b64url(plaintext),
        "payload": sealed.to_json(),
    }


def sealed_vectors() -> list[dict[str, Any]]:
    fpr = fingerprint(TENANT, "bob", ref.public_point(1), ref.public_point(2))
    return [
        sealed_vector(
            tags.CK_WRAP,
            ecies.ck_wrap_context(TENANT, CONVERSATION, KEY_ID, "user", "alice"),
            label_bytes("ck", 32),
        ),
        sealed_vector(
            tags.SHARE, ecies.share_context(TENANT, KEY_ID, 2, "carol"), label_bytes("x2", 32)
        ),
        sealed_vector(
            tags.SUBSHARE, ecies.subshare_context(TENANT, CEREMONY, 1, 3), label_bytes("f13", 32)
        ),
        sealed_vector(
            tags.PARTIAL,
            ecies.partial_context(TENANT, REQUEST, KEY_ID, 3, "bob", fpr),
            label_bytes("partial", 65 + 64),
        ),
    ]


def signature_vector(type_tag: str, fields: tuple[Field, ...]) -> dict[str, Any]:
    signer = scalar(f"{type_tag}-signer")
    return {
        "tag": type_tag,
        "fields": [typed(f) for f in fields],
        "signer_scalar": hex32(signer),
        "signer_pkcs8": b64url(ref.pkcs8(signer)),
        "signer": b64url(ref.public_point(signer)),
        "digest": b64url(signatures.signed_digest(type_tag, *fields)),
        "signature": b64url(signatures.sign_fields(ref.private_key(signer), type_tag, *fields)),
    }


def signature_vectors() -> list[dict[str, Any]]:
    wrap = signatures.wrap_fields(
        TENANT,
        CONVERSATION,
        KEY_ID,
        ref.public_point(scalar("wrap-R")),
        "user",
        "alice",
        fingerprint(TENANT, "alice", ref.public_point(3), ref.public_point(4)),
    )
    return [
        signature_vector(tags.WRAP_SIG, wrap),
        signature_vector(tags.TRANSCRIPT, (label_bytes("transcript", 32),)),
        signature_vector(
            tags.DEALING_SIG,
            signatures.dealing_fields(
                TENANT,
                CEREMONY,
                2,
                (ref.public_point(scalar("deal-a0")), ref.public_point(scalar("deal-a1"))),
                scalar("deal-c"),
                scalar("deal-s"),
            ),
        ),
        signature_vector(
            tags.REQUEST_SIG,
            signatures.request_fields(
                TENANT,
                REQUEST,
                "access",
                CEREMONY,
                "sam",
                "Employee left; the authority needs the record.",
                # Out of order on purpose: both sides must sort to the same fields.
                [(CONVERSATION, KEY_ID), (CEREMONY, REQUEST)],
            ),
        ),
        signature_vector(
            tags.APPROVAL_SIG,
            signatures.approval_fields(
                TENANT, REQUEST, 3, 1, {KEY_ID: '{"v":1}', CEREMONY: '{"v":2}'}
            ),
        ),
    ]


def ceremony_vector() -> dict[str, Any]:
    """k = 2 of n = 3; holders 1 and 2 deal, holder 3 is a paper share."""
    k, holders, dealers = 2, (1, 2, 3), (1, 2)
    polynomials = {j: [scalar(f"f{j}-{t}") for t in range(k)] for j in dealers}
    dealings = []
    for j in dealers:
        c, s = ref.schnorr_prove(TENANT, CEREMONY, j, polynomials[j][0], scalar(f"pok-{j}"))
        dealings.append(Dealing(j, ref.commitments(polynomials[j]), c, s))
    commitment_lists = [dealing.commitments for dealing in dealings]
    recovery_key = recovery_public_key(commitment_lists)
    shares = {i: sum(ref.evaluate(polynomials[j], i) for j in dealers) % ORDER for i in holders}
    public_shares = tuple(holder_public_share(i, commitment_lists) for i in holders)
    participants = tuple(
        Participant(f"holder-{i}", i, label_bytes(f"fpr-{i}", 32)) for i in holders
    )
    gateway_keys = (("gk-1", ref.public_point(scalar("gateway-key"))),)
    transcript = TranscriptInput(
        TENANT,
        CEREMONY,
        k,
        participants,
        tuple(dealings),
        recovery_key,
        public_shares,
        gateway_keys,
    )
    return {
        "tenant_id": TENANT,
        "ceremony_id": CEREMONY,
        "k": k,
        "participants": [
            {"holder_ref": p.holder_ref, "index": p.index, "fingerprint": b64url(p.fingerprint)}
            for p in participants
        ],
        "polynomials": {str(j): [hex32(a) for a in polynomials[j]] for j in dealers},
        "pok_nonces": {str(j): hex32(scalar(f"pok-{j}")) for j in dealers},
        "dealings": [
            {
                "dealer_index": d.dealer_index,
                "commitments": [b64url(c) for c in d.commitments],
                "c": hex32(d.proof_c),
                "s": hex32(d.proof_s),
            }
            for d in dealings
        ],
        "subshares": {
            f"{j}->{i}": hex32(ref.evaluate(polynomials[j], i)) for j in dealers for i in holders
        },
        "shares": {str(i): hex32(shares[i]) for i in holders},
        "recovery_public_key": b64url(recovery_key),
        "recovery_secret": hex32(sum(polynomials[j][0] for j in dealers) % ORDER),
        "holder_shares": [b64url(share) for share in public_shares],
        "gateway_keys": [{"key_id": kid, "public_key": b64url(pub)} for kid, pub in gateway_keys],
        "transcript_hash": b64url(transcript_hash(transcript)),
        "_shares": shares,
        "_recovery_key": recovery_key,
        "_public_shares": public_shares,
    }


def recovery_vector(ceremony: dict[str, Any]) -> dict[str, Any]:
    """A CK wrapped to X, opened from the partials of holders 1 and 3."""
    ck = label_bytes("canary-ck", 32)
    context = ecies.ck_wrap_context(TENANT, CONVERSATION, KEY_ID, "recovery", CEREMONY)
    wrap = ecies.seal(
        tags.CK_WRAP,
        ceremony["_recovery_key"],
        ck,
        context,
        ephemeral_key=ref.private_key(scalar("recovery-ephemeral")),
        nonce=label_bytes("recovery-nonce", 12),
    )
    ephemeral = decode_point(wrap.ephemeral)
    partials = []
    for index in (1, 3):
        partial, c, s = ref.dleq_prove(
            TENANT,
            REQUEST,
            KEY_ID,
            index,
            ceremony["_shares"][index],
            ephemeral,
            scalar(f"dleq-{index}"),
        )
        partials.append(
            {
                "holder_index": index,
                "holder_share": b64url(ceremony["_public_shares"][index - 1]),
                "nonce": hex32(scalar(f"dleq-{index}")),
                "partial": b64url(partial),
                "c": hex32(c),
                "s": hex32(s),
            }
        )
    shared_x = ref.combine_partials(
        [(p["holder_index"], decode_point(from_b64url(p["partial"]))) for p in partials]
    )
    return {
        "request_id": REQUEST,
        "key_id": KEY_ID,
        "conversation_id": CONVERSATION,
        "context": [typed(f) for f in context],
        "wrap": wrap.to_json(),
        "partials": partials,
        "shared_x": b64url(shared_x),
        "ck": b64url(ck),
    }


def private_key_blob_vector() -> dict[str, Any]:
    params = (1024, 1, 1)
    enc_scalar, sig_scalar = scalar("blob-enc"), scalar("blob-sig")
    salt = label_bytes("blob-salt", 16)
    nonces = {"enc": label_bytes("blob-enc-nonce", 12), "sig": label_bytes("blob-sig-nonce", 12)}
    keys = {"enc": ref.pkcs8(enc_scalar), "sig": ref.pkcs8(sig_scalar)}
    blob = ref.seal_private_keys(
        "Kanne Wolke Ferne Tisch 42",
        TENANT,
        "alice",
        keys,
        salt=salt,
        nonces=nonces,
        params=params,
    )
    return {
        "passphrase": "Kanne Wolke Ferne Tisch 42",
        "tenant_id": TENANT,
        "user_sub": "alice",
        "salt": b64url(salt),
        "nonces": {purpose: b64url(nonce) for purpose, nonce in nonces.items()},
        "params": {"m": params[0], "t": params[1], "p": params[2]},
        "enc_pkcs8": b64url(keys["enc"]),
        "sig_pkcs8": b64url(keys["sig"]),
        "enc_pub": b64url(ref.public_point(enc_scalar)),
        "sig_pub": b64url(ref.public_point(sig_scalar)),
        "blob": blob,
    }


def _entry_id(seq: int) -> str:
    return str(uuid.UUID(bytes=label_bytes(f"chain-entry-{seq}", 16), version=4))


def chain_vector() -> dict[str, Any]:
    """Three signed entries; the last, an amendment, has no window (spec A.6, §10.6)."""
    signer = scalar("chain-signer")
    signer_public = ref.public_point(signer)
    signer_id = gateway_key_id(signer_public)
    entries, previous = [], GENESIS
    for seq, (kind, object_type) in enumerate(_CHAIN_KINDS, start=1):
        entry_id = _entry_id(seq)
        entry = seal_entry(
            tenant_id=TENANT,
            conversation_id=CONVERSATION,
            seq=seq,
            entry_id=entry_id,
            kind=kind,  # type: ignore[arg-type]
            window_id=None if kind == "amendment" else WINDOW,
            key_id=KEY_ID,
            objects=(
                ChainObject(
                    object_type,
                    object_key(CONVERSATION, entry_id, object_type),
                    100 + seq,
                    label_bytes(f"chain-object-{seq}", 32).hex(),
                ),
            ),
            prev_hash=previous,
            created_at=datetime(2026, 10, 29, tzinfo=timezone.utc),
            signing_key=ref.private_key(signer),
            signer_key_id=signer_id,
        )
        previous = entry.hash
        entries.append(
            {
                "seq": entry.seq,
                "entry_id": entry.entry_id,
                "kind": entry.kind,
                "window_id": entry.window_id,
                "key_id": entry.key_id,
                "objects": entry.objects,
                "prev_hash": b64url(entry.prev_hash),
                "hash": b64url(entry.hash),
                "signer_key_id": entry.signer_key_id,
                "signature": b64url(entry.signature),
            }
        )
    return {
        "tenant_id": TENANT,
        "conversation_id": CONVERSATION,
        "signer_key_id": signer_id,
        "signer": b64url(signer_public),
        "entries": entries,
    }


def _der_sequence(*items: bytes) -> bytes:
    return _tlv(0x30, b"".join(items))


def timestamp_vector(head: bytes) -> dict[str, Any]:
    """A TimeStampToken as an authority returns it, minus the signer info (spec §11.2)."""
    sha256 = _der_sequence(_tlv(0x06, bytes.fromhex("608648016503040201")), _tlv(0x05, b""))
    info = _der_sequence(
        _integer(1),
        _tlv(0x06, bytes.fromhex("2b0601040181b2310203")),
        _der_sequence(sha256, _tlv(0x04, head)),
        _integer(42),
        _tlv(0x18, b"20261029120000.25Z"),
        _der_sequence(_integer(1)),
        _integer(0x1234_5678),
    )
    encapsulated = _der_sequence(
        _tlv(0x06, bytes.fromhex("2a864886f70d0109100104")), _tlv(0xA0, _tlv(0x04, info))
    )
    signed_data = _der_sequence(_integer(3), _tlv(0x31, b""), encapsulated, _tlv(0x31, b""))
    token = _der_sequence(_tlv(0x06, bytes.fromhex("2a864886f70d010702")), _tlv(0xA0, signed_data))
    return {
        "der": b64url(token),
        "imprint": b64url(head),
        "gen_time": "2026-10-29T12:00:00.250Z",
    }


def build_vectors() -> dict[str, Any]:
    ceremony = ceremony_vector()
    recovery = recovery_vector(ceremony)
    chain = chain_vector()
    for private in ("_shares", "_recovery_key", "_public_shares"):
        ceremony.pop(private)
    return {
        "version": 1,
        "encoding": encoding_vectors(),
        "fingerprint": fingerprint_vector(),
        **envelope_vectors(),
        "sealed": sealed_vectors(),
        "signatures": signature_vectors(),
        "ceremony": ceremony,
        "recovery": recovery,
        "private_key_blob": private_key_blob_vector(),
        "chain": chain,
        "timestamp": timestamp_vector(from_b64url(chain["entries"][-1]["hash"])),
    }


def render() -> str:
    return json.dumps(build_vectors(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    FIXTURE.write_text(render(), encoding="utf-8")
