"""What the pipeline records for the archive (spec §7, "Pipeline gaps to close").

A recorded message keeps the raw machine translation beside the refined one,
why a refinement was rejected, and the model each service says it used.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import requests

from services.api_gateway.message_processing import transform_pipeline_metadata
from services.api_gateway.pipeline_logic import process_text_pipeline, process_wav
from services.api_gateway.speech_services import AUDIO_WAV_MIME
from services.api_gateway.translation_refiner import BaseTranslationRefiner, RefinementOutcome

ASR_INPUT_SHA256 = "c" * 64


def _response(status: int, body: Any = None, *, content: bytes = b"", headers=None):
    response = requests.Response()
    response.status_code = status
    if body is not None:
        response._content = json.dumps(body).encode()
        response.headers["content-type"] = "application/json"
    else:
        response._content = content
    response.headers.update(headers or {})
    return response


class FakeSpeech:
    def transcribe(self, audio: bytes, *, lang: str, debug: bool) -> requests.Response:
        return _response(
            200,
            {
                "text": "Guten Tag",
                "fallback": False,
                "model": "whisper-large-v3-turbo",
                "model_version": "aff26ae4",
                "input_sha256": ASR_INPUT_SHA256,
            },
        )

    def translate(self, payload: Dict[str, Any]) -> requests.Response:
        return _response(
            200,
            {
                "translations": "Good day",
                "model": "facebook/m2m100_1.2B",
                "model_version": "0123abcd",
            },
        )

    def synthesize(self, payload: Dict[str, Any], *, timeout: float) -> requests.Response:
        return _response(
            200,
            content=b"RIFF-tts",
            headers={"content-type": AUDIO_WAV_MIME, "X-TTS-Model": "piper-en"},
        )


class RejectingRefiner(BaseTranslationRefiner):
    is_active = True

    def refine(self, text, source_lang, target_lang, context=None) -> RefinementOutcome:
        return RefinementOutcome(
            text=text,
            changed=False,
            latency_ms=12.0,
            model="qwen3.5-4b",
            rejected_reason="facts_changed",
        )


class ChangingRefiner(BaseTranslationRefiner):
    is_active = True

    def refine(self, text, source_lang, target_lang, context=None) -> RefinementOutcome:
        return RefinementOutcome(text="Good afternoon", changed=True, model="qwen3.5-4b")


def _step(result: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    return next((s for s in result["debug"]["steps"] if s.get("name") == name), None)


def test_the_asr_step_records_the_model_version_and_input_hash_the_service_reports():
    result = process_wav(b"RIFF", "de", "en", speech=FakeSpeech(), refiner=RejectingRefiner())

    asr = _step(result, "asr")
    assert asr["model"] == "whisper-large-v3-turbo"
    assert asr["model_version"] == "aff26ae4"
    assert asr["input_sha256"] == ASR_INPUT_SHA256


def test_the_translation_step_records_the_model_the_service_reports():
    result = process_text_pipeline(
        "Guten Tag", "de", "en", speech=FakeSpeech(), refiner=RejectingRefiner()
    )

    translation = _step(result, "translation")
    assert translation["model"] == "facebook/m2m100_1.2B"
    assert translation["model_version"] == "0123abcd"


def test_the_raw_translation_survives_a_refinement_that_changed_it():
    result = process_text_pipeline(
        "Guten Tag", "de", "en", speech=FakeSpeech(), refiner=ChangingRefiner()
    )

    assert result["translation_text"] == "Good afternoon"
    assert result["raw_translation_text"] == "Good day"


def test_a_rejected_refinement_records_its_status_and_reason():
    result = process_text_pipeline(
        "Guten Tag", "de", "en", speech=FakeSpeech(), refiner=RejectingRefiner()
    )

    refinement = _step(result, "refinement")
    assert refinement["status"] == "rejected"
    assert refinement["rejected_reason"] == "facts_changed"


def test_message_metadata_names_the_reported_models_not_constants():
    result = process_wav(b"RIFF", "de", "en", speech=FakeSpeech(), refiner=RejectingRefiner())

    metadata = transform_pipeline_metadata(result["debug"], "de", "en")

    models = {step["name"]: step["output"].get("model") for step in metadata["steps"]}
    assert models["asr"] == "whisper-large-v3-turbo"
    assert models["translation"] == "facebook/m2m100_1.2B"
