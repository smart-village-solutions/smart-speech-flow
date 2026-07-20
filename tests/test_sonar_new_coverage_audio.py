"""Behavioral coverage for Sonar remediation paths in audio services."""

import base64
import logging
import os
import time
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize(
    "save_function",
    ["save_original_audio", "save_translated_audio"],
)
def test_audio_storage_reports_decode_failures_without_payload(
    monkeypatch, caplog, save_function
):
    from services.api_gateway import audio_storage

    monkeypatch.setattr(
        audio_storage.base64,
        "b64decode",
        lambda _: (_ for _ in ()).throw(ValueError("invalid input")),
    )

    with caplog.at_level(logging.ERROR), pytest.raises(ValueError, match="Invalid base64"):
        getattr(audio_storage, save_function)("message-1", "sensitive-payload")

    assert "Failed to decode base64 audio" in caplog.text
    assert "sensitive-payload" not in caplog.text


@pytest.mark.parametrize(
    "save_function",
    ["save_original_audio", "save_translated_audio"],
)
def test_audio_storage_reports_write_failures_without_target_path(
    monkeypatch, tmp_path, caplog, save_function
):
    from services.api_gateway import audio_storage

    original_dir = tmp_path / "original"
    translated_dir = tmp_path / "translated"
    monkeypatch.setattr(audio_storage, "ORIGINAL_AUDIO_DIR", original_dir)
    monkeypatch.setattr(audio_storage, "TRANSLATED_AUDIO_DIR", translated_dir)
    monkeypatch.setattr(
        audio_storage.Path,
        "write_bytes",
        lambda *_: (_ for _ in ()).throw(OSError("disk unavailable")),
    )

    payload = base64.b64encode(b"audio").decode()
    with caplog.at_level(logging.ERROR), pytest.raises(IOError, match="Failed to save"):
        getattr(audio_storage, save_function)("private-message", payload)

    assert "Failed to save audio file" in caplog.text
    assert "private-message" not in caplog.text


def test_audio_storage_counts_cleanup_errors_for_both_directories(monkeypatch, tmp_path, caplog):
    from services.api_gateway import audio_storage

    original_dir = tmp_path / "original"
    translated_dir = tmp_path / "translated"
    original_dir.mkdir()
    translated_dir.mkdir()
    original_file = original_dir / "input_old.wav"
    translated_file = translated_dir / "old.wav"
    original_file.write_bytes(b"old")
    translated_file.write_bytes(b"old")
    old_timestamp = time.time() - (audio_storage.RETENTION_HOURS + 1) * 3600
    os.utime(original_file, (old_timestamp, old_timestamp))
    os.utime(translated_file, (old_timestamp, old_timestamp))
    monkeypatch.setattr(audio_storage, "ORIGINAL_AUDIO_DIR", original_dir)
    monkeypatch.setattr(audio_storage, "TRANSLATED_AUDIO_DIR", translated_dir)
    monkeypatch.setattr(
        audio_storage.Path,
        "unlink",
        lambda *_: (_ for _ in ()).throw(OSError("read-only")),
    )

    with caplog.at_level(logging.ERROR):
        stats = audio_storage.cleanup_old_audio_files()

    assert stats["errors"] == 2
    assert stats["total_deleted"] == 0
    assert "Failed to delete old original audio" in caplog.text
    assert "Failed to delete old translated audio" in caplog.text


def test_audio_storage_ignores_stat_failures_when_calculating_usage(monkeypatch, caplog):
    from services.api_gateway import audio_storage

    class Directory:
        def mkdir(self, **_kwargs):
            pass

        def glob(self, _pattern):
            return [SimpleNamespace(stat=lambda: (_ for _ in ()).throw(OSError("denied")))]

    monkeypatch.setattr(audio_storage, "ORIGINAL_AUDIO_DIR", Directory())
    monkeypatch.setattr(audio_storage, "TRANSLATED_AUDIO_DIR", Directory())

    with caplog.at_level(logging.ERROR):
        usage = audio_storage.get_disk_usage()

    assert usage["total_files"] == 0
    assert "Failed to stat original audio" in caplog.text
    assert "Failed to stat translated audio" in caplog.text


def test_enhanced_validator_reports_ffmpeg_conversion_and_output_errors(caplog):
    from services.api_gateway.enhanced_audio_validation import EnhancedAudioValidator

    validator = EnhancedAudioValidator()
    validator.ffmpeg_available = True
    validator._convert_with_ffmpeg = lambda *_: (_ for _ in ()).throw(RuntimeError("converter down"))

    with caplog.at_level(logging.ERROR):
        success, _, error, details = validator.validate_and_convert_audio(b"ID3browser-audio")

    assert success is False
    assert "converter down" in error
    assert details["conversion_error"] == "converter down"
    assert "FFmpeg conversion failed" in caplog.text

    caplog.clear()
    validator._convert_with_ffmpeg = lambda *_: b"not-a-wav"
    with caplog.at_level(logging.ERROR):
        success, _, _, details = validator.validate_and_convert_audio(b"ID3broken-audio")

    assert success is False
    assert "conversion_wav_error" in details
    assert "Converted WAV file is invalid" in caplog.text


def test_enhanced_validator_handles_unexpected_ffmpeg_execution_failure(monkeypatch, caplog):
    from services.api_gateway.enhanced_audio_validation import EnhancedAudioValidator
    import services.api_gateway.enhanced_audio_validation as validation

    validator = EnhancedAudioValidator()
    monkeypatch.setattr(
        validation.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("execution failed")),
    )

    with caplog.at_level(logging.ERROR):
        assert validator._convert_with_ffmpeg(b"source", "webm") is None

    assert "FFmpeg conversion failed" in caplog.text
