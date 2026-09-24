"""The TTS step must record the model that synthesised the audio.

The TTS service names that model in `X-TTS-Model` and says in `X-TTS-Fallback`
whether it replaced the configured voice. The text pipeline used to rebuild the
model from its own copy of the voice map instead, so German audio voiced by MMS
was recorded as Thorsten, and the audio pipeline recorded no model at all.
"""

from unittest.mock import Mock, patch

import pytest
from requests.structures import CaseInsensitiveDict

from services.api_gateway.pipeline_logic import process_text_pipeline, process_wav
from tests.pipeline_helpers import pipeline_collaborators, wav_collaborators

AUDIO_WAV_MIME = "audio/wav"


def _asr() -> Mock:
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"text": "hello world", "debug": {"model": "whisper"}}
    return response


def _translation() -> Mock:
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"translations": "Hallo Welt"}
    return response


def _tts(headers: dict[str, str]) -> Mock:
    response = Mock()
    response.status_code = 200
    response.content = b"RIFF"
    # requests matches header names case-insensitively; a plain dict would not.
    response.headers = CaseInsensitiveDict({"Content-Type": AUDIO_WAV_MIME, **headers})
    return response


def _run_text(target_lang: str, tts_response: Mock) -> dict:
    with patch("services.api_gateway.pipeline_logic.requests.post") as post:
        post.side_effect = [_translation(), tts_response]
        return process_text_pipeline(
            "hello world", "en", target_lang, validate_text=False, **pipeline_collaborators()
        )


def _run_audio(target_lang: str, tts_response: Mock) -> dict:
    with patch("services.api_gateway.pipeline_logic.requests.post") as post:
        post.side_effect = [_asr(), _translation(), tts_response]
        return process_wav(
            b"audio", "en", target_lang, validate_audio=False, **wav_collaborators()
        )


def _tts_step(result: dict) -> dict:
    assert result["error"] is False
    return next(step for step in result["debug"]["steps"] if step["step"] == "TTS")


PIPELINES = pytest.mark.parametrize("run", [_run_text, _run_audio], ids=["text", "audio"])


@PIPELINES
@pytest.mark.parametrize(
    ("target_lang", "mms_model"),
    [("de", "facebook/mms-tts-deu"), ("en", "facebook/mms-tts-eng")],
)
def test_a_fallback_voice_is_recorded_as_the_model_that_ran(run, target_lang, mms_model):
    step = _tts_step(
        run(target_lang, _tts({"X-TTS-Model": mms_model, "X-TTS-Fallback": "true"}))
    )

    assert step["model"] == mms_model
    assert step["fallback"] is True


@PIPELINES
@pytest.mark.parametrize(
    ("target_lang", "coqui_model"),
    [("de", "tts_models/de/thorsten/vits"), ("en", "tts_models/en/ljspeech/vits")],
)
def test_the_configured_voice_is_recorded_when_it_ran(run, target_lang, coqui_model):
    step = _tts_step(
        run(target_lang, _tts({"X-TTS-Model": coqui_model, "X-TTS-Fallback": "false"}))
    )

    assert step["model"] == coqui_model
    assert step["fallback"] is False


@PIPELINES
def test_no_model_is_invented_when_the_service_names_none(run):
    step = _tts_step(run("de", _tts({})))

    assert "model" not in step
    assert "fallback" not in step
