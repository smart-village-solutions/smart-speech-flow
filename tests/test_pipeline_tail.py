"""The shared pipeline tail, driven through process_wav and process_text_pipeline (#230).

The speech services are a fake at the SpeechServices port, so these pin what
the pipeline asks of each service, not how HTTP carries it.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import Mock

import pytest

from services.api_gateway.pipeline_logic import process_text_pipeline, process_wav
from services.api_gateway.speech_services import AUDIO_WAV_MIME
from services.api_gateway.translation_refiner import RefinementOutcome


class _Reply:
    def __init__(
        self,
        status_code: int = 200,
        payload: Optional[Dict[str, Any]] = None,
        *,
        content: bytes = b"",
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.content = content
        self.headers = headers or {"content-type": "application/json"}
        self.text = str(self._payload)

    def json(self) -> Dict[str, Any]:
        return self._payload


class FakeSpeech:
    """The SpeechServices port, answering like healthy services."""

    def __init__(self) -> None:
        self.asr_text: Optional[str] = "Guten Tag"
        self.tts_reply = _Reply(content=b"WAV", headers={"content-type": AUDIO_WAV_MIME})
        self.calls: List[str] = []
        self.translate_payloads: List[Dict[str, Any]] = []
        self.tts_calls: List[Dict[str, Any]] = []

    def transcribe(self, audio: bytes, *, lang: str, debug: bool) -> _Reply:
        self.calls.append("asr")
        return _Reply(payload={"text": self.asr_text, "debug": {"model": "asr"}})

    def translate(self, payload: Dict[str, Any]) -> _Reply:
        self.calls.append("translation")
        self.translate_payloads.append(payload)
        return _Reply(payload={"translations": "Good day"})

    def synthesize(self, payload: Dict[str, Any], *, timeout: float) -> _Reply:
        self.calls.append("tts")
        self.tts_calls.append({"payload": payload, "timeout": timeout})
        return self.tts_reply


def _recording_refiner(**outcome: Any) -> SimpleNamespace:
    defaults: Dict[str, Any] = {"text": "Good day", "changed": False, "latency_ms": 1.0}
    return SimpleNamespace(
        is_active=True, refine=Mock(return_value=RefinementOutcome(**{**defaults, **outcome}))
    )


def _run(mode: str, speech: FakeSpeech, refiner: Any, session_id: Optional[str] = "s-1"):
    if mode == "audio":
        return process_wav(b"RIFF-wav", "de", "en", speech=speech, refiner=refiner)
    return process_text_pipeline(
        "Guten Tag", "de", "en", session_id=session_id, speech=speech, refiner=refiner
    )


@pytest.mark.parametrize("mode", ["audio", "text"])
def test_the_refiner_is_told_the_source_and_the_mode(mode):
    refiner = _recording_refiner()

    _run(mode, FakeSpeech(), refiner)

    assert refiner.refine.call_args.args == ("Good day", "de", "en")
    assert refiner.refine.call_args.kwargs == {
        "context": {"original_text": "Guten Tag", "pipeline": mode}
    }


@pytest.mark.parametrize("mode", ["audio", "text"])
def test_a_skipped_refinement_is_recorded_as_skipped(mode):
    refiner = _recording_refiner(skipped_reason="unsupported_target_language", latency_ms=0.0)

    result = _run(mode, FakeSpeech(), refiner)

    [step] = [s for s in result["debug"]["steps"] if s.get("name") == "refinement"]
    assert step["refinement_comparison"]["primary_status"] == "skipped"


@pytest.mark.parametrize("mode", ["audio", "text"])
def test_a_tts_error_body_names_the_failure_and_keeps_the_translation(mode):
    speech = FakeSpeech()
    speech.tts_reply = _Reply(500, {"error": "tts kaputt"})

    result = _run(mode, speech, _recording_refiner())

    assert result["error"] is True
    assert result["error_msg"] == "TTS-Fehler: tts kaputt"
    assert result["translation_text"] == "Good day"
    assert result["debug"]["failed_stage"] == "tts"


@pytest.mark.parametrize("mode", ["audio", "text"])
def test_the_tts_model_header_reaches_the_step(mode):
    speech = FakeSpeech()
    speech.tts_reply = _Reply(
        content=b"WAV", headers={"content-type": AUDIO_WAV_MIME, "X-TTS-Model": "piper/en"}
    )

    result = _run(mode, speech, _recording_refiner())

    assert result["audio_bytes"] == b"WAV"
    assert (result["debug"]["steps"][-1]["model"], result["debug"]["steps"][-1]["language"]) == (
        "piper/en",
        "en",
    )


@pytest.mark.parametrize("mode", ["audio", "text"])
def test_a_raising_tts_keeps_the_work_already_done(mode):
    import requests

    speech = FakeSpeech()
    speech.synthesize = Mock(side_effect=requests.Timeout("tts:8000"))

    result = _run(mode, speech, _recording_refiner())

    assert result["error"] is True
    assert (result["asr_text"], result["translation_text"]) == ("Guten Tag", "Good day")
    assert result["debug"]["error_code"] == "upstream_timeout"
