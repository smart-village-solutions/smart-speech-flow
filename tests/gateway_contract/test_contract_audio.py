"""Audio validation, conversion and storage, as the message routes see them."""

from __future__ import annotations

import hashlib
import io
import math
import os
import struct
import wave
from pathlib import Path

import pytest

from tests.gateway_contract.contract_support import TENANT_A, wav_bytes

pytestmark = pytest.mark.usefixtures("speech_services")

MAX_BYTES = 32 * 1024 * 1024
REQUIRED_SPECS = {
    "sample_rate": 16000,
    "bit_depth": 16,
    "channels": 1,
    "min_duration": 0.1,
    "max_duration": 200.0,
}

NOT_WAV = b"not a wav file at all"
TOO_SHORT = wav_bytes(0.05)
OVERSIZED = b"\0" * (MAX_BYTES + 1)

# What the validator reports for each input, identically on every route.
INVALID_INPUTS = {
    "not_wav": (
        NOT_WAV,
        "INVALID_WAV_FORMAT",
        "Invalid WAV format",
        {},
    ),
    "too_short": (
        TOO_SHORT,
        "INVALID_AUDIO_SPECS",
        "Audio specifications invalid: Duration 0.05s too short, minimum: 0.1s",
        {
            "current_specs": {
                "sample_rate": 16000,
                "bit_depth": 16,
                "channels": 1,
                "duration_seconds": 0.05,
            },
            "required_specs": REQUIRED_SPECS,
        },
    ),
    # One byte over the limit still reads "32.0MB": the size is rounded for display.
    "oversized": (
        OVERSIZED,
        "FILE_TOO_LARGE",
        "Audio file too large: 32.0MB. Maximum allowed: 32.0MB",
        {"file_size_bytes": MAX_BYTES + 1, "max_size_bytes": MAX_BYTES, "file_size_mb": 32.0},
    ),
}


def stereo_44k(seconds: float = 0.5) -> bytes:
    rate = 44100
    frames = b"".join(
        struct.pack("<hh", int(8000 * math.sin(2 * math.pi * 440 * index / rate)), 0)
        for index in range(int(seconds * rate))
    )
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(frames)
    return buffer.getvalue()


def wav_format(data: bytes) -> tuple[int, int, int, int]:
    with wave.open(io.BytesIO(data), "rb") as wav:
        return wav.getframerate(), wav.getnchannels(), wav.getsampwidth() * 8, wav.getnframes()


def audio_root() -> Path:
    """The directory the gateway is configured to store audio in."""
    return Path(os.environ.get("SSF_AUDIO_BASE_DIR", "/data/audio"))


def session_audio_dir(session_id: str) -> Path:
    tenant_ref = hashlib.sha256(TENANT_A.encode("utf-8")).hexdigest()[:12]
    return audio_root() / "v2" / tenant_ref / session_id


@pytest.fixture
def active_session(conversations) -> str:
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    return session_id


def _send_audio(client, session_id: str, body: bytes, role: str = "admin", source: str = "de"):
    target = "en" if source == "de" else "de"
    return client.post(
        f"/api/{role}/session/{session_id}/message",
        files={"file": ("speech.wav", body, "audio/wav")},
        data={"source_lang": source, "target_lang": target},
    )


@pytest.mark.parametrize("kind", list(INVALID_INPUTS))
@pytest.mark.parametrize(("role", "source"), [("admin", "de"), ("customer", "en")])
def test_invalid_audio_messages_are_refused_before_the_pipeline(
    client, active_session, speech_services, kind, role, source
):
    body, error_code, error_message, validation_details = INVALID_INPUTS[kind]

    response = _send_audio(client, active_session, body, role=role, source=source)

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert set(detail) == {"status", "error_code", "error_message", "details", "timestamp"}
    assert (detail["status"], detail["error_code"], detail["error_message"]) == (
        "error",
        error_code,
        error_message,
    )
    assert set(detail["details"]) == {"validation_details", "validation_time_ms"}
    assert detail["details"]["validation_details"] == validation_details
    assert isinstance(detail["details"]["validation_time_ms"], int)
    assert speech_services.calls == []
    listing = client.get(f"/api/admin/session/{active_session}/messages").json()
    assert listing["messages"] == []
    assert not session_audio_dir(active_session).exists()


def test_audio_is_validated_before_the_supported_language_check(
    client, conversations, speech_services
):
    # Activation accepts an unsupported customer language, so the admin's
    # de -> xx matches the session and reaches the supported-language check.
    session_id = conversations.create()
    conversations.activate(session_id, "xx")

    invalid = client.post(
        f"/api/admin/session/{session_id}/message",
        files={"file": ("speech.wav", NOT_WAV, "audio/wav")},
        data={"source_lang": "de", "target_lang": "xx"},
    )
    valid = client.post(
        f"/api/admin/session/{session_id}/message",
        files={"file": ("speech.wav", wav_bytes(), "audio/wav")},
        data={"source_lang": "de", "target_lang": "xx"},
    )

    assert (invalid.status_code, invalid.json()["detail"]["error_code"]) == (
        400,
        "INVALID_WAV_FORMAT",
    )
    assert (valid.status_code, valid.json()["detail"]["error_code"]) == (
        400,
        "UNSUPPORTED_LANGUAGE",
    )
    assert speech_services.calls == []


def test_a_44k_stereo_message_reaches_asr_as_16k_mono(client, active_session, speech_services):
    recording = stereo_44k()
    assert wav_format(recording)[:3] == (44100, 2, 16)

    response = _send_audio(client, active_session, recording)

    assert response.status_code == 200, response.text
    [asr_request] = speech_services.sent_to("asr")
    name, sent, mime = asr_request["files"]["file"]
    assert (name, mime) == ("input.wav", "audio/wav")
    assert wav_format(sent) == (16000, 1, 16, 8000)
    # The message path validates once and hands process_wav the converted audio;
    # the client sees no validation step in the metadata.
    steps = response.json()["pipeline_metadata"]["steps"]
    assert [step["name"] for step in steps] == ["asr", "translation", "tts"]


def test_message_audio_is_stored_in_the_v2_layout_and_served_byte_for_byte(
    client, active_session, speech_services
):
    recording = stereo_44k()

    response = _send_audio(client, active_session, recording)

    assert response.status_code == 200, response.text
    message_id = response.json()["message_id"]
    session_dir = session_audio_dir(active_session)
    original = session_dir / "original" / f"{message_id}.wav"
    translated = session_dir / "translated" / f"{message_id}.wav"
    assert sorted(path for path in session_dir.rglob("*") if path.is_file()) == [
        original,
        translated,
    ]
    # The original is kept as it was uploaded, not as ASR heard it.
    assert original.read_bytes() == recording
    assert translated.read_bytes() == wav_bytes(0.2)
    for role in ("admin", "customer"):
        for variant, stored in (("original", original), ("translated", translated)):
            served = client.get(
                f"/api/{role}/session/{active_session}/audio/{message_id}/{variant}.wav"
            )
            assert served.status_code == 200
            assert served.headers["content-type"] == "audio/wav"
            assert served.content == stored.read_bytes()
