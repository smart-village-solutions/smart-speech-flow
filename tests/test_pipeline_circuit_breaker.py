"""An open breaker has to look like every other pipeline failure.

The pipeline already classifies upstream failures carefully -- failed stage,
a stable telemetry code, and a retryable 503 for the load shedding added in
#190. A breaker refusing to call a service is another transient upstream
failure, so it goes through that machinery rather than around it. Nothing in
the routes or the frontend should need to learn a new shape.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from services.api_gateway import pipeline_logic
from services.api_gateway.ai_service_client import breaker_for
from services.api_gateway.circuit_breaker import CircuitState
from services.api_gateway.pipeline_logic import UPSTREAM_BUSY_ERROR_CODE
from services.api_gateway.quality_telemetry import PipelineStage, QualityErrorCode

WAV_HEADER = b"RIFF" + b"\x00" * 40


def _open(service: str) -> None:
    breaker = breaker_for(service)
    for _ in range(breaker.config.failure_threshold):
        breaker.record_failure("forced open by test")
    assert breaker.state is CircuitState.OPEN


class Reply:
    """A minimal stand-in for the replies the pipeline reads."""

    def __init__(self, payload=None, *, status_code=200, content=b"", headers=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = content
        self.headers = headers or {"content-type": "audio/wav"}
        self.text = ""

    def json(self):
        return self._payload


def _ok_asr():
    return Reply({"text": "guten tag", "debug": {"model": "whisper"}})


def _ok_translation():
    return Reply({"translations": "good day"})


def _ok_tts():
    return Reply(content=b"RIFFaudio", headers={"content-type": "audio/wav"})


class TestAudioPipeline:
    def test_an_open_asr_breaker_fails_the_asr_stage(self):
        _open("asr")

        with patch.object(pipeline_logic.requests, "post") as post:
            result = pipeline_logic.process_wav(WAV_HEADER, "de", "en", validate_audio=False)

        post.assert_not_called(), "a request was sent although the circuit was open"
        assert result["error"] is True
        assert result["debug"]["failed_stage"] == PipelineStage.ASR.value
        assert result["debug"]["error_code"] == QualityErrorCode.UPSTREAM_CIRCUIT_OPEN.value

    def test_the_caller_is_told_to_retry(self):
        _open("asr")

        with patch.object(pipeline_logic.requests, "post"):
            result = pipeline_logic.process_wav(WAV_HEADER, "de", "en", validate_audio=False)

        assert result["error_code"] == UPSTREAM_BUSY_ERROR_CODE
        assert result["retry_after_seconds"] >= 1

    def test_an_open_translation_breaker_keeps_the_transcript(self):
        _open("translation")

        with patch.object(pipeline_logic.requests, "post", return_value=_ok_asr()):
            result = pipeline_logic.process_wav(WAV_HEADER, "de", "en", validate_audio=False)

        assert result["error"] is True
        assert result["debug"]["failed_stage"] == PipelineStage.TRANSLATION.value
        assert result["asr_text"] == "guten tag", "the work already done was discarded"
        assert result["translation_text"] is None

    def test_an_open_tts_breaker_keeps_transcript_and_translation(self):
        _open("tts")
        replies = [_ok_asr(), _ok_translation()]

        with patch.object(pipeline_logic.requests, "post", side_effect=replies):
            result = pipeline_logic.process_wav(WAV_HEADER, "de", "en", validate_audio=False)

        assert result["debug"]["failed_stage"] == PipelineStage.TTS.value
        assert result["asr_text"] == "guten tag"
        assert result["translation_text"] == "good day"
        assert result["audio_bytes"] is None

    def test_the_blocked_stage_is_visible_in_the_debug_trail(self):
        """A stage that silently vanishes is worse than one recorded as skipped."""
        _open("asr")

        with patch.object(pipeline_logic.requests, "post"):
            result = pipeline_logic.process_wav(WAV_HEADER, "de", "en", validate_audio=False)

        steps = result["debug"]["steps"]
        assert any(step.get("name") == "asr" for step in steps), steps


class TestTextPipeline:
    def test_an_open_translation_breaker_fails_the_translation_stage(self):
        _open("translation")

        with patch.object(pipeline_logic.requests, "post") as post:
            result = pipeline_logic.process_text_pipeline(
                "guten tag", "de", "en", validate_text=False
            )

        post.assert_not_called()
        assert result["error"] is True
        assert result["debug"]["failed_stage"] == PipelineStage.TRANSLATION.value
        assert result["error_code"] == UPSTREAM_BUSY_ERROR_CODE

    def test_an_open_tts_breaker_keeps_the_translation(self):
        _open("tts")

        with patch.object(pipeline_logic.requests, "post", return_value=_ok_translation()):
            result = pipeline_logic.process_text_pipeline(
                "guten tag", "de", "en", validate_text=False
            )

        assert result["debug"]["failed_stage"] == PipelineStage.TTS.value
        assert result["translation_text"] == "good day"
        assert result["audio_bytes"] is None


class TestTheHappyPathIsUnchanged:
    def test_a_closed_circuit_runs_the_whole_pipeline(self):
        with patch.object(
            pipeline_logic.requests,
            "post",
            side_effect=[_ok_asr(), _ok_translation(), _ok_tts()],
        ):
            result = pipeline_logic.process_wav(WAV_HEADER, "de", "en", validate_audio=False)

        assert result["error"] is False
        assert result["asr_text"] == "guten tag"
        assert result["translation_text"] == "good day"
        assert result["audio_bytes"] == b"RIFFaudio"

    def test_a_successful_run_is_recorded_against_every_breaker(self):
        """This is the whole point of #219: the numbers come from real traffic."""
        before = {
            name: breaker_for(name).health.successful_requests
            for name in ("asr", "translation", "tts")
        }

        with patch.object(
            pipeline_logic.requests,
            "post",
            side_effect=[_ok_asr(), _ok_translation(), _ok_tts()],
        ):
            pipeline_logic.process_wav(WAV_HEADER, "de", "en", validate_audio=False)

        for name in ("asr", "translation", "tts"):
            assert (
                breaker_for(name).health.successful_requests == before[name] + 1
            ), f"{name} recorded no traffic for a request that reached it"

    @pytest.mark.parametrize("failing_status", [500, 502])
    def test_an_upstream_error_still_produces_its_own_result(self, failing_status):
        """The breaker records it, but the existing classification is unchanged."""
        with patch.object(
            pipeline_logic.requests,
            "post",
            return_value=Reply({"detail": "upstream exploded"}, status_code=failing_status),
        ):
            result = pipeline_logic.process_wav(WAV_HEADER, "de", "en", validate_audio=False)

        assert result["error"] is True
        assert result["debug"]["failed_stage"] == PipelineStage.ASR.value
        assert result["debug"]["error_code"] != QualityErrorCode.UPSTREAM_CIRCUIT_OPEN.value
        assert breaker_for("asr").health.failed_requests == 1
