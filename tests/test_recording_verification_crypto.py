"""Verification records' byte layouts (spec Appendix A.3a)."""

from __future__ import annotations

import hashlib

import pytest

from services.api_gateway.recording.crypto import tags
from services.api_gateway.recording.crypto.encoding import enc
from services.api_gateway.recording.crypto.verification import (
    decision_imprint,
    note_aad,
    notes_digest,
    verification_fields,
)

TENANT, CONVERSATION, VERIFICATION = "t", "c-1", "v-1"


def test_the_note_aad_binds_every_field_and_the_part():
    base = note_aad(TENANT, CONVERSATION, VERIFICATION, "note", "e-1", "k-1")
    assert base == enc(
        tags.VERIFICATION_NOTE, TENANT, CONVERSATION, VERIFICATION, "note", "e-1", "k-1"
    )
    assert base != note_aad(TENANT, CONVERSATION, VERIFICATION, "overall", "e-1", "k-1")
    assert base != note_aad(TENANT, CONVERSATION, "v-2", "note", "e-1", "k-1")
    assert base != note_aad(TENANT, CONVERSATION, VERIFICATION, "note", "e-2", "k-1")


def test_an_unknown_part_is_refused():
    with pytest.raises(ValueError):
        note_aad(TENANT, CONVERSATION, VERIFICATION, "draft", "e-1", "k-1")  # type: ignore[arg-type]


def test_the_digest_hashes_each_ciphertext_in_entry_order():
    first, second = ("b-entry", "k-1", b"\x01" * 70_000), ("a-entry", "k-2", b"\x02" * 40)
    digest = notes_digest(b"\x01overall", [first, second])
    expected = hashlib.sha256(
        enc(
            hashlib.sha256(b"\x01overall").digest(),
            2,
            "a-entry",
            "k-2",
            hashlib.sha256(second[2]).digest(),
            "b-entry",
            "k-1",
            hashlib.sha256(first[2]).digest(),
        )
    ).digest()
    assert digest == expected
    assert notes_digest(b"\x01overall", [second, first]) == digest


def test_no_overall_note_is_an_empty_field():
    digest = notes_digest(None, [])
    assert digest == hashlib.sha256(enc(b"", 0)).digest()
    assert digest != notes_digest(b"", [])  # an empty envelope is not "none"


def test_code_point_order_not_locale_order():
    upper, lower = ("Z", "k", b"\x01"), ("a", "k", b"\x02")
    assert (
        notes_digest(None, [lower, upper])
        == hashlib.sha256(
            enc(
                b"",
                2,
                "Z",
                "k",
                hashlib.sha256(b"\x01").digest(),
                "a",
                "k",
                hashlib.sha256(b"\x02").digest(),
            )
        ).digest()
    )


def test_verification_fields_order_the_snapshot_and_count_it():
    fields = verification_fields(
        TENANT,
        VERIFICATION,
        CONVERSATION,
        b"\x05" * 32,
        "approved",
        b"\x06" * 32,
        ["ssf.recording.review.sworn", "ssf.recording.review"],
    )
    assert fields == (
        TENANT,
        VERIFICATION,
        CONVERSATION,
        b"\x05" * 32,
        "approved",
        b"\x06" * 32,
        2,
        "ssf.recording.review",
        "ssf.recording.review.sworn",
    )


def test_an_unknown_outcome_is_refused():
    with pytest.raises(ValueError):
        verification_fields(TENANT, VERIFICATION, CONVERSATION, b"\x05" * 32, "maybe", b"", [])


def test_the_imprint_covers_digest_and_signature():
    assert (
        decision_imprint(b"\x01" * 32, b"\x02" * 64)
        == hashlib.sha256(b"\x01" * 32 + b"\x02" * 64).digest()
    )
