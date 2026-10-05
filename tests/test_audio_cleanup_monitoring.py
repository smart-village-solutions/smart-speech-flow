"""What the audio retention pass tells Prometheus (#426).

The ssf-audio-storage alerts ask two questions of these series: is the
retention pass still completing, and can it delete what has expired. A count
of deleted files answers neither, since a quiet deployment or
SSF_CONTENT_RETENTION_HOURS=0 deletes nothing on every healthy pass.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry

from services.api_gateway.app import create_app
from services.api_gateway.audio_storage import AudioStorageMetrics, AudioStore, AudioVariant
from services.api_gateway.background_tasks import run_retention_pass
from services.api_gateway.tenant_session import TenantSessionKey

KEY = TenantSessionKey("tenant-a", "SESSION1")
TWO_DAYS_AGO = time.time() - 2 * 24 * 3600


@pytest.fixture(autouse=True)
def default_retention(monkeypatch):
    """The tester setting of 0 would keep every expired file these tests expect gone."""
    monkeypatch.delenv("SSF_CONTENT_RETENTION_HOURS", raising=False)


def _value(registry: CollectorRegistry, name: str, **labels: str) -> float | None:
    return registry.get_sample_value(name, labels)


def _store(tmp_path: Path) -> tuple[AudioStore, CollectorRegistry]:
    registry = CollectorRegistry()
    return AudioStore(tmp_path, AudioStorageMetrics(registry)), registry


def _expired(store: AudioStore, message_id: str = "expired") -> Path:
    path = store.save(KEY, message_id, AudioVariant.ORIGINAL, b"RIFF")
    os.utime(path, (TWO_DAYS_AGO, TWO_DAYS_AGO))
    return path


class _Sessions:
    def sweep_expired_content(self, _now) -> dict:
        return {"refused_removed": 0, "expired_removed": 0}


class _FailingSweep:
    def sweep_expired_content(self, _now) -> dict:
        raise RuntimeError("session store unavailable")


class _FailingStore:
    def cleanup_expired(self) -> dict:
        raise OSError("audio volume unavailable")


def test_every_cleanup_series_is_exposed_at_zero_before_the_first_pass():
    """increase() needs a prior sample, or the first deletion or error is invisible."""
    registry = CollectorRegistry()
    AudioStorageMetrics(registry)

    for directory in ("original", "translated"):
        assert _value(registry, "audio_cleanup_deleted_files_total", directory=directory) == 0
    assert _value(registry, "audio_cleanup_errors_total") == 0


def test_a_completed_retention_pass_records_when_it_ran(tmp_path):
    store, registry = _store(tmp_path)

    before = time.time()
    run_retention_pass(_Sessions(), store)

    ran_at = _value(registry, "audio_cleanup_last_run_timestamp_seconds")
    assert ran_at is not None and before <= ran_at <= time.time()


def test_a_pass_whose_transcript_sweep_fails_does_not_count_as_completed(tmp_path):
    """Transcripts expire on the same pass; audio alone completing is half the promise.

    The gauge reads 0 until a pass completes, which the alert sees as stale.
    """
    store, registry = _store(tmp_path)

    run_retention_pass(_FailingSweep(), store)

    assert _value(registry, "audio_cleanup_last_run_timestamp_seconds") == 0


def test_a_pass_with_retention_disabled_still_records_that_it_ran(tmp_path, monkeypatch):
    monkeypatch.setenv("SSF_CONTENT_RETENTION_HOURS", "0")
    store, registry = _store(tmp_path)
    kept = _expired(store)

    run_retention_pass(_Sessions(), store)

    assert kept.exists()
    assert _value(registry, "audio_cleanup_last_run_timestamp_seconds") > 0


@pytest.mark.skipif(os.geteuid() == 0, reason="root deletes from a read-only directory")
def test_an_expired_file_cleanup_cannot_delete_is_counted(tmp_path):
    """The shape of the root-owned audio volume: the pass runs and every unlink fails."""
    store, registry = _store(tmp_path)
    stuck = _expired(store)
    stuck.parent.chmod(0o555)
    try:
        store.cleanup_expired()
    finally:
        stuck.parent.chmod(0o755)

    assert stuck.exists()
    assert _value(registry, "audio_cleanup_errors_total") == 1
    assert _value(registry, "audio_cleanup_deleted_files_total", directory="original") == 0


def test_a_failed_retention_pass_does_not_raise():
    """The lifespan runs one before serving; a broken volume must not refuse startup."""
    run_retention_pass(_Sessions(), _FailingStore())


def test_the_gateway_runs_a_retention_pass_before_it_serves(tmp_path, monkeypatch):
    for variable in ("REDIS_URL", "SSF_DEPLOYMENT_ENV"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("SSF_AUDIO_BASE_DIR", str(tmp_path))
    expired = _expired(AudioStore(tmp_path))
    app = create_app()
    before = time.time()

    with TestClient(app) as client:
        assert not expired.exists()
        scrape = client.get("/metrics").text

    assert 'audio_cleanup_deleted_files_total{directory="original"} 1.0' in scrape
    ran_at = re.search(r"^audio_cleanup_last_run_timestamp_seconds (\S+)$", scrape, re.MULTILINE)
    assert ran_at is not None and float(ran_at.group(1)) >= before
    assert 'audio_files_total{directory="original"} 0.0' in scrape
