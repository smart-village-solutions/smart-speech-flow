"""The plaintext of archived objects (spec §7, §7.1)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from services.api_gateway.recording.records import (
    consent_record,
    encode,
    message_record,
    playback_record,
)

ACCEPTED = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
COMPLETED = datetime(2026, 10, 27, 12, 0, 3, tzinfo=timezone.utc)

RESULT = {
    "error": False,
    "asr_text": "Guten Tag",
    "translation_text": "Good afternoon",
    "raw_translation_text": "Good day",
    "debug": {
        "steps": [
            {"step": "Text_Validation", "output": True},
            {
                "name": "asr",
                "output": "Guten Tag",
                "model": "whisper-large-v3-turbo",
                "model_version": "aff2",
                "input_sha256": "cc" * 32,
                "started_at": "a",
                "completed_at": "b",
                "duration_ms": 900,
            },
            {"name": "translation", "output": "Good day", "model": "m2m", "model_version": "01"},
            {
                "name": "refinement",
                "input": {"enabled": True, "changed": True},
                "output": "Good afternoon",
                "model": "qwen",
                "status": "success",
                "rejected_reason": None,
            },
            {"name": "tts", "model": "piper-en", "fallback": False},
        ]
    },
}


def _record(result=RESULT, original=b"RIFF-in", translated=b"RIFF-out"):
    return message_record(
        message_id="m1",
        sender="customer",
        source_lang="de",
        target_lang="en",
        source_text="Guten Tag",
        result=result,
        original_audio=original,
        translated_audio=translated,
        accepted_at=ACCEPTED,
        completed_at=COMPLETED,
    )


def test_a_message_record_keeps_the_raw_and_final_translation():
    record = _record()

    assert record["source_text"] == "Guten Tag"
    assert record["raw_translation"] == "Good day"
    assert record["final_text"] == "Good afternoon"
    assert "error" not in record


def test_a_message_record_names_every_steps_model_and_skips_validation():
    steps = {step["name"]: step for step in _record()["steps"]}

    assert set(steps) == {"asr", "translation", "refinement", "tts"}
    assert steps["asr"]["model_version"] == "aff2"
    assert steps["translation"]["model"] == "m2m"
    assert steps["refinement"]["changed"] is True
    assert steps["tts"]["model"] == "piper-en"


def test_a_message_record_hashes_both_audios_and_the_asr_input():
    hashes = _record()["hashes"]

    assert hashes == {
        "original_audio_sha256": hashlib.sha256(b"RIFF-in").hexdigest(),
        "asr_input_sha256": "cc" * 32,
        "translated_audio_sha256": hashlib.sha256(b"RIFF-out").hexdigest(),
    }


def test_a_typed_message_is_text_input_without_audio_hashes():
    record = _record(original=None)

    assert record["input"] == "text"
    assert record["hashes"]["original_audio_sha256"] is None


def test_a_failed_message_keeps_its_stage_and_code_and_no_final_text():
    failed = {
        "error": True,
        "error_msg": "Translation-Fehler: 500",
        "error_code": None,
        "asr_text": "Guten Tag",
        "debug": {"steps": [], "failed_stage": "translation", "error_code": "upstream_5xx"},
    }

    record = _record(result=failed, translated=None)

    assert record["final_text"] is None
    assert record["error"] == {
        "stage": "translation",
        "code": "upstream_5xx",
        "message": "Translation-Fehler: 500",
    }


def test_records_encode_canonically_and_keep_non_ascii_text():
    encoded = encode({"b": "Grüße", "a": 1})

    assert encoded == '{"a":1,"b":"Grüße"}'.encode()
    assert json.loads(encoded) == {"a": 1, "b": "Grüße"}


def test_a_consent_record_names_the_request_the_answer_and_the_basis():
    record = consent_record(
        request_id="r1",
        request_kind="first",
        requested_by="alice",
        requested_at=ACCEPTED,
        answered_at=COMPLETED,
        window_id="w1",
        legal_basis="consent",
    )

    assert record["answer"] == "yes"
    assert record["requested_by"] == "alice"
    assert record["legal_basis"] == "consent"
    assert record["answered_at"] == COMPLETED.isoformat(timespec="microseconds")


def test_a_playback_record_refers_to_the_message_entry():
    record = playback_record(
        message_id="m1", message_entry_id="e1", event="completed", reported_by="admin", at=COMPLETED
    )

    assert record["message_entry_id"] == "e1"
    assert record["event"] == "completed"
