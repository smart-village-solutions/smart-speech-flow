"""All of a submission's free text in one envelope; rows from before 004 stay readable."""

from uuid import uuid4

import pytest

from services.api_gateway.feedback.crypto import FeedbackCipher
from services.api_gateway.feedback.text_answers import (
    LEGACY_TEXT_ID,
    open_text_answers,
    seal_text_answers,
)

SENTINEL = "PURPLE-RHINOCEROS-9317-SENTINEL"
CIPHER = FeedbackCipher(key=b"0" * 32)


def test_text_answers_round_trip() -> None:
    feedback_id = uuid4()
    answers = {"improvementIdeas": f"Say {SENTINEL}", "notes": "Grüße, ok"}

    envelope = seal_text_answers(CIPHER, answers, feedback_id=feedback_id, tenant_id="t")

    assert envelope is not None
    assert SENTINEL.encode() not in envelope
    assert (
        open_text_answers(CIPHER, envelope, legacy=False, feedback_id=feedback_id, tenant_id="t")
        == answers
    )


def test_no_text_answers_seal_nothing() -> None:
    assert seal_text_answers(CIPHER, {}, feedback_id=uuid4(), tenant_id="t") is None


def test_no_envelope_opens_to_no_answers() -> None:
    assert open_text_answers(CIPHER, None, legacy=False, feedback_id=uuid4(), tenant_id="t") == {}


@pytest.mark.parametrize("moved", ["feedback", "tenant"])
def test_an_envelope_cannot_move_to_another_row(moved: str) -> None:
    feedback_id = uuid4()
    envelope = seal_text_answers(CIPHER, {"a": "b"}, feedback_id=feedback_id, tenant_id="t")
    assert envelope is not None

    with pytest.raises(ValueError):
        open_text_answers(
            CIPHER,
            envelope,
            legacy=False,
            feedback_id=uuid4() if moved == "feedback" else feedback_id,
            tenant_id="other" if moved == "tenant" else "t",
        )


def test_a_legacy_envelope_reads_as_the_improvement_ideas() -> None:
    """Migration 004 moves the old single-string ciphertext unchanged."""
    feedback_id = uuid4()
    envelope = CIPHER.encrypt("old text", feedback_id=feedback_id, tenant_id="t")

    assert open_text_answers(
        CIPHER, envelope, legacy=True, feedback_id=feedback_id, tenant_id="t"
    ) == {LEGACY_TEXT_ID: "old text"}


def test_a_legacy_text_that_looks_like_json_stays_text() -> None:
    feedback_id = uuid4()
    envelope = CIPHER.encrypt('{"notes": "x"}', feedback_id=feedback_id, tenant_id="t")

    assert open_text_answers(
        CIPHER, envelope, legacy=True, feedback_id=feedback_id, tenant_id="t"
    ) == {LEGACY_TEXT_ID: '{"notes": "x"}'}


@pytest.mark.parametrize(
    "plaintext", [f'["{SENTINEL}"]', f'{{"a": 1, "b": "{SENTINEL}"}}', SENTINEL, f'"{SENTINEL}"']
)
def test_a_malformed_envelope_is_refused_without_its_text(plaintext: str) -> None:
    feedback_id = uuid4()
    envelope = CIPHER.encrypt(plaintext, feedback_id=feedback_id, tenant_id="t")

    with pytest.raises(ValueError) as caught:
        open_text_answers(CIPHER, envelope, legacy=False, feedback_id=feedback_id, tenant_id="t")

    assert SENTINEL not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None or caught.value.__suppress_context__
