"""What a guest's yes must carry, against the policy read at the yes (spec §6, §20)."""

from __future__ import annotations

import base64
from datetime import datetime, timezone

import pytest

from services.api_gateway.recording.consent_evidence import (
    SIGNATURE_MAX_BYTES,
    ConsentEvidenceError,
    GuestAnswer,
    decode_signature,
    evidence,
)
from services.api_gateway.recording.consent_text import consent_text
from services.api_gateway.recording.session_state import Phase, RecordingState
from services.api_gateway.studio_v2 import RecordingPolicy
from tests.test_recording_session_service import POLICY_FIELDS

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
CHECKED_AT = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def _policy(**fields: str) -> RecordingPolicy:
    return RecordingPolicy.model_validate(POLICY_FIELDS | fields)


def _asked(kind: str = "first", **fields) -> RecordingState:
    return RecordingState(
        phase=Phase.ASKING, request_id="r1", request_kind=kind, requested_by="emp", **fields
    )


def _answer(policy: RecordingPolicy, kind: str = "first", **fields) -> GuestAnswer:
    digest = consent_text(policy, "ar", kind).sha256
    return GuestAnswer(**({"language": "ar", "text_sha256": digest, "name": "Amira"} | fields))


def _refused(policy, asked, answer) -> tuple[str, int]:
    with pytest.raises(ConsentEvidenceError) as raised:
        evidence(policy, asked, answer)
    return raised.value.code, raised.value.status


@pytest.mark.parametrize("digest", [None, "0" * 64], ids=["missing", "other-text"])
def test_a_hash_that_is_not_the_served_texts_is_refused(digest) -> None:
    policy = _policy()
    answer = _answer(policy, text_sha256=digest)
    assert _refused(policy, _asked(), answer) == ("CONSENT_TEXT_MISMATCH", 409)


def test_the_hash_is_of_the_guests_language() -> None:
    policy = _policy()
    answer = _answer(policy, language="fa")  # an Arabic hash for a Persian session
    assert _refused(policy, _asked(), answer)[0] == "CONSENT_TEXT_MISMATCH"


def test_a_first_yes_records_text_german_text_name_signature_and_id_check() -> None:
    policy = _policy(signature="optional", idCheck="optional")
    fields = evidence(policy, _asked(id_checked_at=CHECKED_AT), _answer(policy, signature_png=PNG))
    assert fields["text"] == consent_text(policy, "ar", "first").record()
    assert fields["text_de"] == consent_text(policy, "de", "first").record()
    assert fields["guest"] == {"name": "Amira", "entered_by": "guest"}
    assert fields["signature"] == {
        "policy": "optional",
        "given": True,
        "png": base64.b64encode(PNG).decode(),
    }
    assert fields["id_check"] == {
        "policy": "optional",
        "checked": True,
        "at": CHECKED_AT.isoformat(),
    }


def test_a_resume_carries_the_text_alone() -> None:
    policy = _policy(signature="required")
    fields = evidence(policy, _asked("resume"), _answer(policy, "resume", name=None))
    assert set(fields) == {"text", "text_de"}
    assert fields["text"]["kind"] == "resume"


@pytest.mark.parametrize(
    "name", [None, "", "   ", "x" * 201], ids=["none", "empty", "blank", "long"]
)
def test_a_first_yes_needs_a_name(name) -> None:
    policy = _policy()
    assert _refused(policy, _asked(), _answer(policy, name=name))[0] == "NAME_REQUIRED"


@pytest.mark.parametrize(
    ("proposed", "sent", "entered_by"),
    [("Amira", " Amira ", "employee"), ("Amira", "Amira H.", "guest"), (None, "Amira", "guest")],
)
def test_the_name_says_who_entered_it(proposed, sent, entered_by) -> None:
    policy = _policy()
    fields = evidence(policy, _asked(proposed_name=proposed), _answer(policy, name=sent))
    assert fields["guest"]["entered_by"] == entered_by
    assert fields["guest"]["name"] == sent.strip()


@pytest.mark.parametrize(
    ("mode", "sent", "cannot_sign", "recorded"),
    [
        ("off", PNG, False, {"policy": "off", "given": False}),
        ("optional", None, False, {"policy": "optional", "given": False, "fallback": None}),
        ("required", None, True, {"policy": "required", "given": False, "fallback": "tap"}),
    ],
    ids=["off-ignores-a-drawing", "optional-unsigned", "required-tap-fallback"],
)
def test_the_signature_follows_the_policy(mode, sent, cannot_sign, recorded) -> None:
    policy = _policy(signature=mode)
    answer = _answer(policy, signature_png=sent, cannot_sign=cannot_sign)
    assert evidence(policy, _asked(), answer)["signature"] == recorded


def test_a_required_signature_needs_a_drawing_or_the_tap_fallback() -> None:
    policy = _policy(signature="required")
    assert _refused(policy, _asked(), _answer(policy))[0] == "SIGNATURE_REQUIRED"


def test_an_unchecked_id_is_recorded_as_such() -> None:
    policy = _policy(idCheck="off")
    assert evidence(policy, _asked(), _answer(policy))["id_check"] == {
        "policy": "off",
        "checked": False,
        "at": None,
    }


def test_a_signature_is_a_png_of_bounded_size() -> None:
    assert decode_signature(None) is None
    assert decode_signature(base64.b64encode(PNG).decode()) == PNG
    for bad in (
        "not base64!",
        base64.b64encode(b"GIF89a" + b"\x00" * 8).decode(),
        base64.b64encode(PNG + b"\x00" * SIGNATURE_MAX_BYTES).decode(),
    ):
        with pytest.raises(ConsentEvidenceError) as raised:
            decode_signature(bad)
        assert (raised.value.code, raised.value.status) == ("INVALID_SIGNATURE", 422)
