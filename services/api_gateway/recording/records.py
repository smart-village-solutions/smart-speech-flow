"""The plaintext of archived JSON objects (spec §6, §7, §7.1).

These dictionaries exist only in memory: each is encrypted under the
conversation key before it reaches the spool. Plaintext hashes live here,
inside the encrypted object, never outside it (§11.1).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final, Literal

RECORD_VERSION: Final[int] = 1

PlaybackEvent = Literal["started", "completed"]

# The fields each pipeline step contributes, beyond its name and timings.
_STEP_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "asr": ("output", "model", "model_version", "input_sha256", "error"),
    "translation": ("output", "model", "model_version", "error"),
    "refinement": ("output", "model", "status", "rejected_reason", "skipped_reason", "error"),
    "tts": ("model", "fallback", "error"),
}
_TIMING_FIELDS: Final[tuple[str, ...]] = ("started_at", "completed_at", "duration_ms")


def encode(record: Mapping[str, Any]) -> bytes:
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def _sha256(data: bytes | None) -> str | None:
    return None if data is None else hashlib.sha256(data).hexdigest()


def _time(at: datetime) -> str:
    return at.isoformat(timespec="microseconds")


def _steps(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    steps = []
    for step in (result.get("debug") or {}).get("steps", []):
        name = step.get("name")
        if name not in _STEP_FIELDS:
            continue  # validation steps carry nothing a reviewer needs
        kept = {"name": name}
        kept.update({field: step.get(field) for field in _TIMING_FIELDS + _STEP_FIELDS[name]})
        if name == "refinement":
            kept["changed"] = (step.get("input") or {}).get("changed", False)
        steps.append(kept)
    return steps


def _asr_input_sha256(result: Mapping[str, Any]) -> str | None:
    for step in (result.get("debug") or {}).get("steps", []):
        if step.get("name") == "asr":
            digest = step.get("input_sha256")
            return digest if isinstance(digest, str) else None
    return None


def message_record(
    *,
    message_id: str,
    sender: str,
    source_lang: str,
    target_lang: str,
    source_text: str | None,
    result: Mapping[str, Any],
    original_audio: bytes | None,
    translated_audio: bytes | None,
    accepted_at: datetime,
    completed_at: datetime,
) -> dict[str, Any]:
    """`record.json` of a stored or failed message: everything but the audio itself."""
    failed = bool(result.get("error"))
    record: dict[str, Any] = {
        "v": RECORD_VERSION,
        "message_id": message_id,
        "sender": sender,
        "input": "audio" if original_audio is not None else "text",
        "source_lang": source_lang,
        "target_lang": target_lang,
        "accepted_at": _time(accepted_at),
        "completed_at": _time(completed_at),
        "source_text": source_text,
        "raw_translation": result.get("raw_translation_text"),
        "final_text": None if failed else result.get("translation_text"),
        "steps": _steps(result),
        "hashes": {
            "original_audio_sha256": _sha256(original_audio),
            "asr_input_sha256": _asr_input_sha256(result),
            "translated_audio_sha256": _sha256(translated_audio),
        },
    }
    if failed:
        debug = result.get("debug") or {}
        record["error"] = {
            "stage": debug.get("failed_stage"),
            "code": result.get("error_code") or debug.get("error_code"),
            "message": result.get("error_msg"),
        }
    return record


def consent_record(
    *,
    request_id: str,
    request_kind: str,
    requested_by: str,
    requested_at: datetime | None,
    answered_at: datetime,
    window_id: str | None,
    legal_basis: str,
    answer: Literal["yes", "no"] = "yes",
) -> dict[str, Any]:
    """`consent.json` of an answer. 3C adds the name, signature, text hash and ID check."""
    return {
        "v": RECORD_VERSION,
        "request_id": request_id,
        "kind": request_kind,
        "requested_by": requested_by,
        "requested_at": _time(requested_at) if requested_at else None,
        "answered_at": _time(answered_at),
        "answer": answer,
        "window_id": window_id,
        "legal_basis": legal_basis,
    }


def playback_record(
    *,
    message_id: str,
    message_entry_id: str,
    event: PlaybackEvent,
    reported_by: str,
    at: datetime,
) -> dict[str, Any]:
    """`playback.json`: the receiving screen's report, as its own entry (§7.1)."""
    return {
        "v": RECORD_VERSION,
        "message_id": message_id,
        "message_entry_id": message_entry_id,
        "event": event,
        "reported_by": reported_by,
        "at": _time(at),
    }
