"""What the audio retention pass tells Prometheus (#426).

The ssf-audio-storage alerts ask two questions of these series: is the
retention pass still completing, and can it delete what has expired. A count
of deleted files answers neither, since a quiet deployment or
SSF_CONTENT_RETENTION_HOURS=0 deletes nothing on every healthy pass.
"""

from __future__ import annotations

import os
import re
import threading
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
LAST_RUN = "audio_cleanup_last_run_timestamp_seconds"
not_root = pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory modes")


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
    def __init__(self, failed: int = 0) -> None:
        self.failed = failed
        self.swept_on: threading.Thread | None = None

    def sweep_expired_content(self, _now) -> dict:
        self.swept_on = threading.current_thread()
        return {"refused_removed": 0, "expired_removed": 0, "failed": self.failed}


class _RaisingSweep:
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


def test_the_last_run_clock_starts_when_the_gateway_does():
    """Not at 0: in real time that is decades stale, and the alert would skip its 2.5h."""
    before = time.time()
    registry = CollectorRegistry()
    AudioStorageMetrics(registry)

    started = _value(registry, LAST_RUN)
    assert started is not None and before <= started <= time.time()


async def test_a_completed_retention_pass_records_when_it_ran(tmp_path):
    store, registry = _store(tmp_path)
    started = _value(registry, LAST_RUN)

    time.sleep(0.01)
    await run_retention_pass(_Sessions(), store)

    assert _value(registry, LAST_RUN) > started


@pytest.mark.parametrize(
    "sessions", [_RaisingSweep(), _Sessions(failed=1)], ids=["raises", "reports-a-failure"]
)
async def test_a_pass_whose_transcript_sweep_fails_does_not_count_as_completed(tmp_path, sessions):
    """Transcripts expire on the same pass; audio alone completing is half the promise."""
    store, registry = _store(tmp_path)
    started = _value(registry, LAST_RUN)

    await run_retention_pass(sessions, store)

    assert _value(registry, LAST_RUN) == started


async def test_a_failing_sweep_still_records_disk_usage(tmp_path):
    """The size alerts read these gauges; a broken session store must not blind them."""
    store, registry = _store(tmp_path)
    store.save(KEY, "kept", AudioVariant.ORIGINAL, b"RIFF")

    await run_retention_pass(_RaisingSweep(), store)

    assert _value(registry, "audio_files_total", directory="original") == 1


async def test_a_failing_audio_cleanup_still_sweeps_transcripts():
    sessions = _Sessions()

    await run_retention_pass(sessions, _FailingStore())

    assert sessions.swept_on is not None


async def test_file_work_leaves_the_event_loop_and_the_sweep_stays_on_it(tmp_path):
    """The sweep mutates session state the loop's handlers share; the walk does not."""
    store, _registry = _store(tmp_path)
    walked_on: list[threading.Thread] = []
    cleanup = store.cleanup_expired
    store.cleanup_expired = lambda: walked_on.append(threading.current_thread()) or cleanup()
    sessions = _Sessions()

    await run_retention_pass(sessions, store)

    assert walked_on and walked_on[0] is not threading.current_thread()
    assert sessions.swept_on is threading.current_thread()


async def test_a_pass_with_retention_disabled_still_records_that_it_ran(tmp_path, monkeypatch):
    monkeypatch.setenv("SSF_CONTENT_RETENTION_HOURS", "0")
    store, registry = _store(tmp_path)
    kept = _expired(store)
    started = _value(registry, LAST_RUN)

    time.sleep(0.01)
    await run_retention_pass(_Sessions(), store)

    assert kept.exists()
    assert _value(registry, LAST_RUN) > started


@not_root
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


@not_root
def test_a_directory_cleanup_cannot_read_is_counted(tmp_path):
    """A walk that skips what it cannot list would report a clean pass over kept files."""
    store, registry = _store(tmp_path)
    hidden = _expired(store).parents[1]
    hidden.chmod(0o000)
    try:
        store.cleanup_expired()
    finally:
        hidden.chmod(0o755)

    assert _value(registry, "audio_cleanup_errors_total") == 1


def test_a_file_already_gone_is_not_a_failed_deletion(tmp_path, monkeypatch):
    """Off the loop, termination can delete a file between the walk and the unlink."""
    store, registry = _store(tmp_path)
    _expired(store)

    def already_gone(self, missing_ok=False):
        raise FileNotFoundError(self)

    monkeypatch.setattr(Path, "unlink", already_gone)
    store.cleanup_expired()

    assert _value(registry, "audio_cleanup_errors_total") == 0


async def test_a_failed_retention_pass_does_not_raise():
    """The lifespan runs one before serving; a broken volume must not refuse startup."""
    await run_retention_pass(_RaisingSweep(), _FailingStore())


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
    ran_at = re.search(rf"^{LAST_RUN} (\S+)$", scrape, re.MULTILINE)
    assert ran_at is not None and float(ran_at.group(1)) >= before
    assert 'audio_files_total{directory="original"} 0.0' in scrape
