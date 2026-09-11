"""The envelope that keeps feedback free text unreadable at rest.

A database dump, a stray backup, or a misdirected row must not yield readable
feedback. These tests pin that property rather than the algorithm.
"""

import base64
import os
from uuid import uuid4

import pytest

from services.api_gateway.feedback.crypto import (
    FEEDBACK_KEY_ENV,
    FeedbackCipher,
    MissingEncryptionKey,
)

TENANT = "tenant-a"


@pytest.fixture
def cipher() -> FeedbackCipher:
    return FeedbackCipher(key=b"0" * 32)


def test_round_trip_returns_the_original_text(cipher: FeedbackCipher) -> None:
    feedback_id = uuid4()
    text = "The translator misunderstood a medical term."

    envelope = cipher.encrypt(text, feedback_id=feedback_id, tenant_id=TENANT)
    restored = cipher.decrypt(envelope, feedback_id=feedback_id, tenant_id=TENANT)

    assert restored == text


def test_the_envelope_does_not_contain_the_plaintext(cipher: FeedbackCipher) -> None:
    """The whole point: a database dump must not be readable."""
    text = "a distinctive sentence nobody else would write"

    envelope = cipher.encrypt(text, feedback_id=uuid4(), tenant_id=TENANT)

    assert text.encode("utf-8") not in envelope


def test_same_text_encrypts_differently_each_time(cipher: FeedbackCipher) -> None:
    """A deterministic ciphertext would leak which submissions matched."""
    feedback_id = uuid4()
    text = "identical text"

    first = cipher.encrypt(text, feedback_id=feedback_id, tenant_id=TENANT)
    second = cipher.encrypt(text, feedback_id=feedback_id, tenant_id=TENANT)

    assert first != second


def test_a_row_moved_to_another_feedback_id_fails_to_decrypt(
    cipher: FeedbackCipher,
) -> None:
    """AAD binding: a moved ciphertext must fail, not silently decrypt."""
    envelope = cipher.encrypt("text", feedback_id=uuid4(), tenant_id=TENANT)

    with pytest.raises(ValueError):
        cipher.decrypt(envelope, feedback_id=uuid4(), tenant_id=TENANT)


def test_a_row_moved_to_another_tenant_fails_to_decrypt(
    cipher: FeedbackCipher,
) -> None:
    feedback_id = uuid4()
    envelope = cipher.encrypt("text", feedback_id=feedback_id, tenant_id=TENANT)

    with pytest.raises(ValueError):
        cipher.decrypt(envelope, feedback_id=feedback_id, tenant_id="tenant-b")


def test_a_tampered_envelope_fails_to_decrypt(cipher: FeedbackCipher) -> None:
    """Authenticated encryption: a flipped bit must be detected."""
    feedback_id = uuid4()
    envelope = bytearray(cipher.encrypt("text", feedback_id=feedback_id, tenant_id=TENANT))
    envelope[-1] ^= 0x01

    with pytest.raises(ValueError):
        cipher.decrypt(bytes(envelope), feedback_id=feedback_id, tenant_id=TENANT)


def test_the_envelope_carries_a_key_version(cipher: FeedbackCipher) -> None:
    """Rotation later must not require re-encrypting every stored row."""
    envelope = cipher.encrypt("text", feedback_id=uuid4(), tenant_id=TENANT)

    assert envelope[0] == 1


def test_an_unknown_envelope_version_is_rejected(cipher: FeedbackCipher) -> None:
    feedback_id = uuid4()
    envelope = bytearray(cipher.encrypt("text", feedback_id=feedback_id, tenant_id=TENANT))
    envelope[0] = 99

    with pytest.raises(ValueError):
        cipher.decrypt(bytes(envelope), feedback_id=feedback_id, tenant_id=TENANT)


def test_unicode_survives_the_round_trip(cipher: FeedbackCipher) -> None:
    """Feedback arrives in ten languages, including RTL scripts."""
    feedback_id = uuid4()
    text = "الترجمة كانت غير دقيقة — 😀 ትግርኛ"

    envelope = cipher.encrypt(text, feedback_id=feedback_id, tenant_id=TENANT)

    assert cipher.decrypt(envelope, feedback_id=feedback_id, tenant_id=TENANT) == text


def test_a_missing_key_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    """No random fallback: it would encrypt rows nobody can ever read."""
    monkeypatch.delenv(FEEDBACK_KEY_ENV, raising=False)

    with pytest.raises(MissingEncryptionKey):
        FeedbackCipher.from_environment()


def test_a_short_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(FEEDBACK_KEY_ENV, base64.b64encode(b"tooshort").decode())

    with pytest.raises(MissingEncryptionKey):
        FeedbackCipher.from_environment()


def test_a_non_base64_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(FEEDBACK_KEY_ENV, "not-base64-!!!")

    with pytest.raises(MissingEncryptionKey):
        FeedbackCipher.from_environment()


def test_from_environment_reads_a_base64_key(monkeypatch: pytest.MonkeyPatch) -> None:
    key = os.urandom(32)
    monkeypatch.setenv(FEEDBACK_KEY_ENV, base64.b64encode(key).decode())

    cipher = FeedbackCipher.from_environment()
    feedback_id = uuid4()

    envelope = cipher.encrypt("text", feedback_id=feedback_id, tenant_id=TENANT)
    assert cipher.decrypt(envelope, feedback_id=feedback_id, tenant_id=TENANT) == "text"
