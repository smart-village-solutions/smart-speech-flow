"""Behavioral coverage for Sonar remediation paths in audio services."""

import base64
import logging
import os
import time
from types import SimpleNamespace

import pytest


def raise_value_error(_: str) -> None:
    raise ValueError("invalid input")


def raise_os_error(*_: object) -> None:
    raise OSError("disk unavailable")


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
        raise_value_error,
    )
    save_audio = getattr(audio_storage, save_function)

    with caplog.at_level(logging.ERROR), pytest.raises(ValueError, match="Invalid base64"):
        save_audio("message-1", "sensitive-payload")

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
        raise_os_error,
    )

    payload = base64.b64encode(b"audio").decode()
    save_audio = getattr(audio_storage, save_function)
    with caplog.at_level(logging.ERROR), pytest.raises(IOError, match="Failed to save"):
        save_audio("private-message", payload)

    assert "Failed to save audio file" in caplog.text
    assert "private-message" not in caplog.text


def test_audio_storage_counts_cleanup_errors_for_both_directories(monkeypatch, tmp_path, caplog):
    from services.api_gateway import audio_storage
    from services.api_gateway.tenant_session import TenantSessionKey

    key = TenantSessionKey("tenant-a", "ABC12345")
    original_file = audio_storage.save_audio(
        key,
        "original-old",
        audio_storage.AudioVariant.ORIGINAL,
        b"old",
        base_dir=tmp_path,
    )
    translated_file = audio_storage.save_audio(
        key,
        "translated-old",
        audio_storage.AudioVariant.TRANSLATED,
        b"old",
        base_dir=tmp_path,
    )
    old_timestamp = time.time() - (audio_storage.RETENTION_HOURS + 1) * 3600
    os.utime(original_file, (old_timestamp, old_timestamp))
    os.utime(translated_file, (old_timestamp, old_timestamp))
    monkeypatch.setattr(
        audio_storage.Path,
        "unlink",
        lambda *_: (_ for _ in ()).throw(OSError("read-only")),
    )

    with caplog.at_level(logging.ERROR):
        stats = audio_storage.cleanup_old_audio_files(base_dir=tmp_path)

    assert stats["errors"] == 2
    assert stats["total_deleted"] == 0
    assert caplog.text.count("Failed to delete expired v2 audio") == 2


def test_audio_storage_ignores_stat_failures_when_calculating_usage(monkeypatch, caplog, tmp_path):
    from services.api_gateway import audio_storage

    denied = SimpleNamespace(
        stat=lambda: (_ for _ in ()).throw(OSError("denied"))
    )
    monkeypatch.setattr(
        audio_storage,
        "_managed_v2_audio_files",
        lambda _base_dir: iter(
            [
                (audio_storage.AudioVariant.ORIGINAL, denied),
                (audio_storage.AudioVariant.TRANSLATED, denied),
            ]
        ),
    )

    with caplog.at_level(logging.ERROR):
        usage = audio_storage.get_disk_usage(base_dir=tmp_path)

    assert usage["total_files"] == 0
    assert caplog.text.count("Failed to stat v2 audio") == 2


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
