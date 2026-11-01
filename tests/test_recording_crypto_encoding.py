"""Canonical encoding, point validation and object envelopes refuse what they must (spec §20)."""

from __future__ import annotations

import pytest

from services.api_gateway.recording.crypto import aead
from services.api_gateway.recording.crypto.curve import (
    GENERATOR,
    InvalidPoint,
    decode_point,
    encode_point,
)
from services.api_gateway.recording.crypto.encoding import enc, from_b64url


def test_enc_refuses_what_has_no_canonical_form():
    with pytest.raises(TypeError):
        enc(True)
    with pytest.raises(ValueError):
        enc(-1)
    with pytest.raises(ValueError):
        enc(b"x" * 65536)


def test_enc_keeps_field_boundaries():
    assert enc("ab", "c") != enc("a", "bc")


@pytest.mark.parametrize("text", ["AA==", "AA+/", "A", "A A"])
def test_base64url_is_strict(text):
    with pytest.raises(ValueError):
        from_b64url(text)


def test_off_curve_compressed_and_identity_points_are_rejected():
    x, y = GENERATOR
    off_curve = b"\x04" + x.to_bytes(32, "big") + (y + 1).to_bytes(32, "big")
    # Valid on the curve, but the spec allows the uncompressed form only.
    compressed = bytes([2 + y % 2]) + x.to_bytes(32, "big")
    # On the curve and 65 bytes long, but with the hybrid prefix: only the prefix check refuses it.
    hybrid = bytes([6 + y % 2]) + encode_point(GENERATOR)[1:]
    for raw in (off_curve, compressed, hybrid, b"\x00", encode_point(GENERATOR)[:33]):
        with pytest.raises(InvalidPoint):
            decode_point(raw)


def test_an_object_moved_to_another_entry_fails_to_open():
    key = bytes(32)
    sealed = aead.seal(key, b"audio", aead.object_aad("t", "c", "e1", "original.wav", "k"))
    with pytest.raises(aead.EnvelopeError):
        aead.open_(key, sealed, aead.object_aad("t", "c", "e2", "original.wav", "k"))
