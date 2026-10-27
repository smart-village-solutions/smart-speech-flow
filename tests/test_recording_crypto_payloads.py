"""Sealed payloads and signatures are bound to their type and context (spec §20)."""

from __future__ import annotations

import pytest

from services.api_gateway.recording.crypto import ecies, signatures, tags
from tests import recording_crypto_reference as ref

TENANT, KEY = "t1", "k1"


def _sealed_share():
    recipient = 7
    context = ecies.share_context(TENANT, KEY, 2, "carol")
    sealed = ecies.seal(tags.SHARE, ref.public_point(recipient), b"s" * 32, context)
    return sealed, ref.private_key(recipient), context


def test_a_payload_is_refused_as_another_type():
    sealed, _, _ = _sealed_share()
    with pytest.raises(ecies.SealedPayloadError):
        ecies.Sealed.from_json(sealed.to_json(), expected_type=tags.CK_WRAP)


def test_a_relabelled_payload_fails_to_open():
    sealed, key, context = _sealed_share()
    relabelled = ecies.Sealed(tags.CK_WRAP, sealed.ephemeral, sealed.nonce, sealed.ciphertext)
    with pytest.raises(ecies.SealedPayloadError):
        ecies.open_with_private_key(relabelled, key, context)


def test_a_swapped_context_field_fails_to_open():
    sealed, key, _ = _sealed_share()
    with pytest.raises(ecies.SealedPayloadError):
        ecies.open_with_private_key(sealed, key, ecies.share_context(TENANT, KEY, 3, "carol"))


def test_sealing_refuses_a_non_payload_tag():
    with pytest.raises(ecies.SealedPayloadError):
        ecies.seal(tags.OBJECT, ref.public_point(7), b"x", ())


def test_a_signature_does_not_verify_under_another_tag_or_field():
    signer = ref.private_key(11)
    signature = signatures.sign_fields(signer, tags.WRAP_SIG, "t", "c")
    public = ref.public_point(11)
    assert signatures.verify_fields(public, signature, tags.WRAP_SIG, "t", "c")
    assert not signatures.verify_fields(public, signature, tags.CHAIN_SIG, "t", "c")
    assert not signatures.verify_fields(public, signature, tags.WRAP_SIG, "t", "d")
    assert not signatures.verify_fields(public, bytes(64), tags.WRAP_SIG, "t", "c")
    assert not signatures.verify_fields(public, signature[:63], tags.WRAP_SIG, "t", "c")
