"""Guards for the audio pipeline's failure path and its duration bookkeeping.

The audio path used to leave three gaps that make any instrumentation built on
top of it report confident nonsense: a non-200 ASR reply was never checked, so a
failed transcription became an empty but "successful" translation; failure rows
carried no millisecond duration and no completion timestamp, so they could not
be compared with success rows; and the two duration fields were read from two
separate clock samples, so they disagreed.
"""

from unittest.mock import Mock, patch

import pytest

from services.api_gateway.pipeline_logic import (
    UPSTREAM_BUSY_ERROR_CODE,
    _finalize_pipeline_success,
    _mark_pipeline_failure,
    process_wav,
)

AUDIO_WAV_MIME = "audio/wav"


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


class TestAudioPipelineAsrFailure:
    """process_wav must treat a failed ASR as a pipeline failure, not as silence."""

    @patch("services.api_gateway.pipeline_logic.requests.post")
    def test_a_non_200_asr_reply_fails_the_pipeline(self, mock_post):
        asr = Mock()
        asr.status_code = 500
        asr.json.return_value = {"error": "model not loaded"}
        # Translation and TTS are stubbed so the defect is observable as a
        # "successful" empty result rather than as a StopIteration.
        mock_post.side_effect = [asr, _ok_translation(), _ok_tts()]

        result = process_wav(b"not-really-audio", "en", "de", validate_audio=False)

        assert result["error"] is True
        assert "ASR" in result["error_msg"]
        assert result["translation_text"] is None
        assert result["audio_bytes"] is None

    @patch("services.api_gateway.pipeline_logic.requests.post")
    def test_a_503_from_asr_keeps_its_transient_meaning(self, mock_post):
        asr = Mock()
        asr.status_code = 503
        asr.headers = {"Retry-After": "7"}
        asr.json.return_value = {"detail": "overloaded"}
        mock_post.side_effect = [asr, _ok_translation(), _ok_tts()]

        result = process_wav(b"not-really-audio", "en", "de", validate_audio=False)

        assert result["error"] is True
        assert result["error_code"] == UPSTREAM_BUSY_ERROR_CODE
        assert result["retry_after_seconds"] == 7

    @patch("services.api_gateway.pipeline_logic.requests.post")
    def test_an_unparseable_asr_reply_fails_the_pipeline_instead_of_raising(self, mock_post):
        asr = Mock()
        asr.status_code = 200
        asr.json.side_effect = ValueError("Expecting value: line 1 column 1")
        mock_post.side_effect = [asr, _ok_translation(), _ok_tts()]

        result = process_wav(b"not-really-audio", "en", "de", validate_audio=False)

        assert result["error"] is True
        assert result["audio_bytes"] is None

    @patch("services.api_gateway.pipeline_logic.requests.post")
    def test_an_asr_transport_error_fails_the_pipeline_instead_of_raising(self, mock_post):
        mock_post.side_effect = OSError("connection reset by peer")

        result = process_wav(b"not-really-audio", "en", "de", validate_audio=False)

        assert result["error"] is True
        assert result["audio_bytes"] is None


class TestFailureFinalisation:
    """A failure row must carry the same duration bookkeeping as a success row."""

    def test_a_failed_pipeline_records_a_millisecond_duration(self):
        debug_info = {"steps": []}

        _mark_pipeline_failure(debug_info, 0.0, "ASR-Fehler: boom")

        assert isinstance(debug_info["total_duration_ms"], int)

    def test_a_failed_pipeline_records_its_completion_timestamp(self):
        debug_info = {"steps": []}

        _mark_pipeline_failure(debug_info, 0.0, "ASR-Fehler: boom")

        assert debug_info["pipeline_completed_at"].endswith("Z")

    @patch("services.api_gateway.pipeline_logic.requests.post")
    def test_a_failed_audio_pipeline_reports_both_durations(self, mock_post):
        asr = Mock()
        asr.status_code = 500
        asr.json.return_value = {"error": "model not loaded"}
        mock_post.side_effect = [asr, _ok_translation(), _ok_tts()]

        result = process_wav(b"not-really-audio", "en", "de", validate_audio=False)

        assert result["error"] is True
        assert isinstance(result["debug"]["total_duration_ms"], int)
        assert "pipeline_completed_at" in result["debug"]


class TestSingleClockRead:
    """Both duration fields must come from one perf_counter sample, not two.

    A monotonically advancing fake clock makes a second read visibly disagree
    with the first, which is exactly the drift the production code had.
    """

    @staticmethod
    def _advancing_clock():
        counter = {"reads": 0}

        def perf_counter() -> float:
            counter["reads"] += 1
            return float(counter["reads"])

        return perf_counter

    def test_success_finalisation_reads_the_clock_once(self, monkeypatch):
        monkeypatch.setattr(
            "services.api_gateway.pipeline_logic.time.perf_counter",
            self._advancing_clock(),
        )
        debug_info = {"steps": []}

        _finalize_pipeline_success(debug_info, 0.0)

        assert debug_info["total_duration_ms"] == pytest.approx(debug_info["total_duration"] * 1000)

    def test_failure_finalisation_reads_the_clock_once(self, monkeypatch):
        monkeypatch.setattr(
            "services.api_gateway.pipeline_logic.time.perf_counter",
            self._advancing_clock(),
        )
        debug_info = {"steps": []}

        _mark_pipeline_failure(debug_info, 0.0, "ASR-Fehler: boom")

        assert debug_info["total_duration_ms"] == pytest.approx(debug_info["total_duration"] * 1000)
