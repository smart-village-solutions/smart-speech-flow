"""Every pipeline exit must name the stage that ended it and why.

`translation_message` telemetry stores `failed_stage` and `error_code` as closed
enums. Both have to come from the pipeline itself: the only other sources are
`debug["steps"]`, whose entries carry the transcript and the source text, and
`error_msg`, which carries the raw upstream reply. Parsing either to work out
what failed would route content through the emitter, which is exactly what the
allowlist exists to prevent.
"""

from unittest.mock import Mock, patch

import pytest
from requests import exceptions

from services.api_gateway.pipeline_logic import (
    process_text_pipeline,
    process_wav,
)
from services.api_gateway.quality_telemetry import PipelineStage, QualityErrorCode

AUDIO_WAV_MIME = "audio/wav"


def _ok_asr(text: str = "hello world") -> Mock:
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"text": text, "debug": {"model": "whisper"}}
    return response


def _ok_translation() -> Mock:
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"translations": "Hallo Welt"}
    return response


def _ok_tts() -> Mock:
    response = Mock()
    response.status_code = 200
    response.content = b"fake-audio"
    response.headers = {"content-type": AUDIO_WAV_MIME}
    return response


def _failing(status_code: int, payload: dict | None = None) -> Mock:
    response = Mock()
    response.status_code = status_code
    response.headers = {}
    response.json.return_value = payload if payload is not None else {"detail": "boom"}
    response.text = "boom"
    return response


def _stage(result: dict) -> str:
    return result["debug"]["failed_stage"]


def _code(result: dict) -> str:
    return result["debug"]["error_code"]


class TestAudioPipelineStageAndCode:
    @patch("services.api_gateway.pipeline_logic.requests.post")
    def test_a_failed_asr_names_the_asr_stage(self, mock_post):
        mock_post.side_effect = [_failing(500), _ok_translation(), _ok_tts()]

        result = process_wav(b"audio", "en", "de", validate_audio=False)

        assert _stage(result) == PipelineStage.ASR.value
        assert _code(result) == QualityErrorCode.UPSTREAM_ERROR.value

    @patch("services.api_gateway.pipeline_logic.requests.post")
    def test_a_shed_asr_load_is_upstream_busy_not_a_generic_error(self, mock_post):
        mock_post.side_effect = [_failing(503), _ok_translation(), _ok_tts()]

        result = process_wav(b"audio", "en", "de", validate_audio=False)

        assert _stage(result) == PipelineStage.ASR.value
        assert _code(result) == QualityErrorCode.UPSTREAM_BUSY.value

    @patch("services.api_gateway.pipeline_logic.requests.post")
    def test_a_failed_translation_names_the_translation_stage(self, mock_post):
        mock_post.side_effect = [_ok_asr(), _failing(500), _ok_tts()]

        result = process_wav(b"audio", "en", "de", validate_audio=False)

        assert _stage(result) == PipelineStage.TRANSLATION.value
        assert _code(result) == QualityErrorCode.UPSTREAM_ERROR.value

    @patch("services.api_gateway.pipeline_logic.requests.post")
    def test_a_failed_tts_names_the_tts_stage(self, mock_post):
        mock_post.side_effect = [_ok_asr(), _ok_translation(), _failing(500)]

        result = process_wav(b"audio", "en", "de", validate_audio=False)

        assert _stage(result) == PipelineStage.TTS.value
        assert _code(result) == QualityErrorCode.UPSTREAM_ERROR.value

    @patch("services.api_gateway.pipeline_logic.requests.post")
    def test_an_unreachable_service_is_unknown_stage_but_a_typed_code(self, mock_post):
        # The blanket handler cannot know which call raised, and guessing would
        # attribute an ASR outage to whichever stage happened to run last.
        mock_post.side_effect = exceptions.ConnectionError("no route to host")

        result = process_wav(b"audio", "en", "de", validate_audio=False)

        assert _stage(result) == PipelineStage.UNKNOWN.value
        assert _code(result) == QualityErrorCode.UPSTREAM_UNREACHABLE.value

    @patch("services.api_gateway.pipeline_logic.requests.post")
    def test_a_successful_run_records_no_failure(self, mock_post):
        mock_post.side_effect = [_ok_asr(), _ok_translation(), _ok_tts()]

        result = process_wav(b"audio", "en", "de", validate_audio=False)

        assert result.get("error") is not True
        assert _stage(result) == PipelineStage.NONE.value
        assert _code(result) == QualityErrorCode.NONE.value


class TestTextPipelineStageAndCode:
    @patch("services.api_gateway.pipeline_logic.requests.post")
    def test_a_failed_translation_names_the_translation_stage(self, mock_post):
        mock_post.side_effect = [_failing(500), _ok_tts()]

        result = process_text_pipeline("hello", "en", "de")

        assert _stage(result) == PipelineStage.TRANSLATION.value
        assert _code(result) == QualityErrorCode.UPSTREAM_ERROR.value

    @patch("services.api_gateway.pipeline_logic.requests.post")
    def test_a_failed_tts_names_the_tts_stage(self, mock_post):
        mock_post.side_effect = [_ok_translation(), _failing(500)]

        result = process_text_pipeline("hello", "en", "de")

        assert _stage(result) == PipelineStage.TTS.value
        assert _code(result) == QualityErrorCode.UPSTREAM_ERROR.value

    @patch("services.api_gateway.pipeline_logic.requests.post")
    def test_rejected_text_names_the_validation_stage(self, mock_post):
        mock_post.side_effect = [_ok_translation(), _ok_tts()]

        result = process_text_pipeline("", "en", "de")

        assert result["error"] is True
        assert _stage(result) == PipelineStage.VALIDATION.value
        assert _code(result) == QualityErrorCode.TEXT_VALIDATION_FAILED.value

    @patch("services.api_gateway.pipeline_logic.requests.post")
    def test_harmful_text_is_content_rejected_not_a_shape_problem(self, mock_post):
        mock_post.side_effect = [_ok_translation(), _ok_tts()]

        result = process_text_pipeline("how to bomb making", "en", "de")

        assert result["error"] is True
        assert _stage(result) == PipelineStage.VALIDATION.value
        assert _code(result) == QualityErrorCode.CONTENT_REJECTED.value

    @patch("services.api_gateway.pipeline_logic.requests.post")
    def test_a_successful_run_records_no_failure(self, mock_post):
        mock_post.side_effect = [_ok_translation(), _ok_tts()]

        result = process_text_pipeline("hello", "en", "de")

        assert result.get("error") is not True
        assert _stage(result) == PipelineStage.NONE.value
        assert _code(result) == QualityErrorCode.NONE.value


class TestEveryExitIsTyped:
    """A stage or code outside the enums would be stored as an empty string."""

    @pytest.mark.parametrize(
        "invoke",
        [
            pytest.param(
                lambda: process_wav(b"audio", "en", "de", validate_audio=False),
                id="audio",
            ),
            pytest.param(lambda: process_text_pipeline("hello", "en", "de"), id="text"),
        ],
    )
    @patch("services.api_gateway.pipeline_logic.requests.post")
    def test_recorded_values_are_always_taxonomy_members(self, mock_post, invoke):
        mock_post.side_effect = exceptions.ReadTimeout("timed out")

        result = invoke()

        assert _stage(result) in {member.value for member in PipelineStage}
        assert _code(result) in {member.value for member in QualityErrorCode}
        assert _code(result) == QualityErrorCode.UPSTREAM_TIMEOUT.value
