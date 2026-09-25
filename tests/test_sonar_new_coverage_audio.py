"""Behavioral coverage for Sonar remediation paths in audio services."""

import logging
import os
import time
from types import SimpleNamespace


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
