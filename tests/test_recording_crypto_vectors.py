"""The gateway reproduces and accepts every shared crypto vector.

The browser suite checks the same file; together they are the interop
contract of spec Appendix A.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from services.api_gateway.recording.chain import ChainEntry, chain_is_intact
from services.api_gateway.recording.crypto import aead, ecies, signatures
from services.api_gateway.recording.crypto.curve import decode_point
from services.api_gateway.recording.crypto.encoding import Field, enc, from_b64url
from services.api_gateway.recording.crypto.proofs import (
    holder_public_share,
    lagrange_at_zero,
    recovery_public_key,
    verify_dleq,
    verify_schnorr,
    verify_share_proof,
    verify_subshare,
)
from services.api_gateway.recording.crypto.signatures import participants_digest
from services.api_gateway.recording.resharing_model import contribution
from services.api_gateway.recording.crypto.transcript import (
    Dealing,
    Participant,
    TranscriptInput,
    display_fingerprint,
    fingerprint,
    paper_device_fingerprint,
    transcript_hash,
)
from services.api_gateway.recording.timestamps import _tst_info
from tests import recording_crypto_reference as ref
from tests.recording_crypto_vectors import FIXTURE, render

VECTORS: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))


def b(text: str) -> bytes:
    return from_b64url(text)


def n(text: str) -> int:
    return int(text, 16)


def fields(typed: list[dict[str, Any]]) -> tuple[Field, ...]:
    out: list[Field] = []
    for item in typed:
        ((kind, value),) = item.items()
        out.append(b(value) if kind == "b" else value)
    return tuple(out)


def test_the_committed_file_is_what_the_generator_produces():
    assert FIXTURE.read_text(encoding="utf-8") == render()


@pytest.mark.parametrize("case", VECTORS["encoding"])
def test_canonical_encoding(case):
    assert enc(*fields(case["fields"])).hex() == case["hex"]


def test_fingerprint_and_its_display():
    case = VECTORS["fingerprint"]
    raw = fingerprint(case["tenant_id"], case["user_sub"], b(case["enc_pub"]), b(case["sig_pub"]))
    assert raw == b(case["fingerprint"])
    assert display_fingerprint(raw) == case["display"]
    paper = case["paper_device"]
    assert paper_device_fingerprint(case["tenant_id"], b(paper["device_pub"])) == b(
        paper["fingerprint"]
    )


def test_object_envelope_opens_under_its_associated_data():
    case = VECTORS["object"]
    aad = aead.object_aad(
        case["tenant_id"],
        case["conversation_id"],
        case["entry_id"],
        case["object_type"],
        case["key_id"],
    )
    assert aead.open_(b(case["key"]), b(case["envelope"]), aad) == b(case["plaintext"])


def test_server_layer_opens_for_its_user():
    case = VECTORS["server_layer"]
    aad = aead.server_layer_aad(case["tenant_id"], case["user_sub"])
    assert aead.open_(b(case["key"]), b(case["envelope"]), aad) == b(case["plaintext"])


@pytest.mark.parametrize("case", VECTORS["sealed"], ids=lambda case: case["type"])
def test_sealed_payloads_open_with_the_recipient_key(case):
    sealed = ecies.Sealed.from_json(case["payload"], expected_type=case["type"])
    opened = ecies.open_with_private_key(
        sealed, ref.private_key(n(case["recipient_scalar"])), fields(case["context"])
    )
    assert opened == b(case["plaintext"])


@pytest.mark.parametrize("case", VECTORS["signatures"], ids=lambda case: case["tag"])
def test_signatures_are_reproduced_and_verify(case):
    signed = fields(case["fields"])
    assert signatures.signed_digest(case["tag"], *signed) == b(case["digest"])
    signer = ref.private_key(n(case["signer_scalar"]))
    assert signatures.sign_fields(signer, case["tag"], *signed) == b(case["signature"])
    assert signatures.verify_fields(b(case["signer"]), b(case["signature"]), case["tag"], *signed)


def test_ceremony_proofs_subshares_and_transcript():
    case = VECTORS["ceremony"]
    dealings = [
        Dealing(d["dealer_index"], tuple(b(c) for c in d["commitments"]), n(d["c"]), n(d["s"]))
        for d in case["dealings"]
    ]
    for dealing in dealings:
        assert verify_schnorr(
            case["tenant_id"],
            case["ceremony_id"],
            dealing.dealer_index,
            dealing.commitments[0],
            dealing.proof_c,
            dealing.proof_s,
        )
    by_dealer = {d.dealer_index: d.commitments for d in dealings}
    for route, value in case["subshares"].items():
        dealer, holder = (int(part) for part in route.split("->"))
        assert verify_subshare(holder, n(value), by_dealer[dealer])
    commitment_lists = [d.commitments for d in dealings]
    assert recovery_public_key(commitment_lists) == b(case["recovery_public_key"])
    assert ref.public_point(n(case["recovery_secret"])) == b(case["recovery_public_key"])
    for index, expected in enumerate(case["holder_shares"], start=1):
        assert holder_public_share(index, commitment_lists) == b(expected)
        assert ref.public_point(n(case["shares"][str(index)])) == b(expected)
    transcript = TranscriptInput(
        case["tenant_id"],
        case["ceremony_id"],
        case["k"],
        tuple(
            Participant(p["holder_ref"], p["index"], b(p["fingerprint"]))
            for p in case["participants"]
        ),
        tuple(dealings),
        b(case["recovery_public_key"]),
        tuple(b(share) for share in case["holder_shares"]),
        tuple((g["key_id"], b(g["public_key"])) for g in case["gateway_keys"]),
    )
    assert transcript_hash(transcript) == b(case["transcript_hash"])


def test_recovery_partials_verify_and_combine_to_the_wrap_key():
    case = VECTORS["recovery"]
    tenant = VECTORS["ceremony"]["tenant_id"]
    wrap = ecies.Sealed.from_json(case["wrap"], expected_type="ssf-rec/ck-wrap/v1")
    for partial in case["partials"]:
        assert verify_dleq(
            tenant,
            case["request_id"],
            case["key_id"],
            partial["holder_index"],
            (b(partial["holder_share"]), wrap.ephemeral, b(partial["partial"])),
            n(partial["c"]),
            n(partial["s"]),
        )
    shared_x = ref.combine_partials(
        [(p["holder_index"], decode_point(b(p["partial"]))) for p in case["partials"]]
    )
    assert shared_x == b(case["shared_x"])
    recovery_key = b(VECTORS["ceremony"]["recovery_public_key"])
    opened = ecies.open_with_shared_x(wrap, shared_x, recovery_key, fields(case["context"]))
    assert opened == b(case["ck"])


def test_private_key_blob_opens_with_the_passphrase():
    case = VECTORS["private_key_blob"]
    opened = ref.open_private_keys(
        case["blob"], case["passphrase"], case["tenant_id"], case["user_sub"]
    )
    assert opened == {"enc": b(case["enc_pkcs8"]), "sig": b(case["sig_pkcs8"])}


def test_the_chain_vector_is_an_intact_signed_chain():
    v = VECTORS["chain"]
    entries = [
        ChainEntry(
            tenant_id=v["tenant_id"],
            conversation_id=v["conversation_id"],
            seq=e["seq"],
            entry_id=e["entry_id"],
            kind=e["kind"],
            window_id=e["window_id"],
            key_id=e["key_id"],
            objects=e["objects"],
            prev_hash=b(e["prev_hash"]),
            hash=b(e["hash"]),
            signer_key_id=e["signer_key_id"],
            signature=b(e["signature"]),
            created_at=None,  # type: ignore[arg-type]  # not signed
        )
        for e in v["entries"]
    ]
    assert [e.kind for e in entries] == ["consent", "message", "amendment"]
    assert entries[-1].window_id is None
    assert chain_is_intact(entries, {v["signer_key_id"]: b(v["signer"])})


def test_the_timestamp_vector_names_the_chain_head():
    v = VECTORS["timestamp"]
    fields_ = _tst_info(b(v["der"]))
    head = b(VECTORS["chain"]["entries"][-1]["hash"])
    assert b(v["imprint"]) == head
    assert head in fields_[2][2]


def test_a_resharing_keeps_x_and_its_new_holders_prove_their_shares():
    """Spec §9.7: C_i0 == λ_i·X_i, Σ C_i0 == X, and the share proof verifies."""
    first, case = VECTORS["ceremony"], VECTORS["resharing"]
    dealers = case["dealers"]
    for dealer in dealers:
        old_public = b(first["holder_shares"][dealer - 1])
        assert b(case["contributions"][str(dealer)]) == contribution(dealer, dealers, old_public)
        assert n(case["lagrange"][str(dealer)]) == lagrange_at_zero(dealer, dealers)
    lists = [tuple(b(c) for c in d["commitments"]) for d in case["dealings"]]
    assert recovery_public_key(lists) == b(first["recovery_public_key"])
    for dealing in case["dealings"]:
        index = dealing["dealer_index"]
        assert b(dealing["commitments"][0]) == b(case["contributions"][str(index)])
        assert verify_schnorr(
            "tenant-kassel", case["ceremony_id"], index, b(dealing["commitments"][0]),
            n(dealing["c"]), n(dealing["s"]),
        )
    proof = case["share_proof"]
    public = b(case["holder_shares"][proof["holder_index"] - 1])
    assert verify_share_proof(
        "tenant-kassel", case["ceremony_id"], proof["holder_index"], public,
        n(proof["c"]), n(proof["s"]),
    )
    digest = participants_digest(
        [(p["index"], p["holder_ref"], b(p["fingerprint"])) for p in case["participants"]]
    )
    assert digest == b(case["participants_digest"])
