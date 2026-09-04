"""Lifespan wiring: the gateway must survive bad telemetry config and clean up.

These are the only tests that run the real lifespan. Every other telemetry test
installs `app.state.quality_telemetry` by hand, which is exactly why the env
parsing and the provider teardown went unnoticed.
"""

import threading
import time

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.quality_telemetry import TelemetryMode
from services.api_gateway.translation_refiner import translation_refiner


def _batch_threads() -> list[str]:
    return [t.name for t in threading.enumerate() if "OtelBatch" in t.name]


@pytest.fixture(autouse=True)
def _quiet_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("SSF_AUDIO_BASE_DIR", str(tmp_path))


@pytest.mark.parametrize("bad_mode", ["true", "1", "on", "", "  ", "PROBE!"])
def test_an_unknown_mode_disables_telemetry_instead_of_killing_the_gateway(
    monkeypatch: pytest.MonkeyPatch, bad_mode: str
) -> None:
    """Telemetry is optional; the gateway is not. A typo must not stop startup."""
    monkeypatch.setenv("SSF_QUALITY_TELEMETRY_MODE", bad_mode)

    with TestClient(app):
        assert app.state.quality_telemetry.mode is TelemetryMode.DISABLED


def test_a_valid_mode_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SSF_QUALITY_TELEMETRY_MODE", "  PROBE  ")

    with TestClient(app):
        assert app.state.quality_telemetry.mode is TelemetryMode.PROBE


def test_disabled_mode_builds_no_exporter_and_starts_no_export_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default must not pay for an SDK provider it will never use."""
    monkeypatch.setenv("SSF_QUALITY_TELEMETRY_MODE", "disabled")
    before = _batch_threads()

    with TestClient(app):
        assert _batch_threads() == before
        assert app.state.quality_telemetry_exporter is None


def test_probe_mode_shuts_its_export_thread_down_on_lifespan_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One leaked thread per startup, and unflushed events, without this."""
    monkeypatch.setenv("SSF_QUALITY_TELEMETRY_MODE", "probe")
    before = _batch_threads()

    with TestClient(app):
        assert len(_batch_threads()) == len(before) + 1

    assert _batch_threads() == before


@pytest.mark.parametrize(
    "variable, value",
    [
        ("OTEL_EXPORTER_OTLP_TIMEOUT", "10s"),
        ("OTEL_EXPORTER_OTLP_LOGS_TIMEOUT", "not-a-number"),
        ("OTEL_EXPORTER_OTLP_COMPRESSION", "gzip2"),
        ("OTEL_EXPORTER_OTLP_LOGS_COMPRESSION", "deflate!"),
    ],
)
def test_a_malformed_otlp_env_var_disables_telemetry_instead_of_crashlooping(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    """OTLPLogExporter parses these itself and raises ValueError on a bad value.

    `10s` is the plausible typo: every other timeout in SSF's compose files is
    written with a unit. The mode parser is hardened against exactly this class
    of operator mistake, and the exporter it builds must be too.
    """
    monkeypatch.setenv("SSF_QUALITY_TELEMETRY_MODE", "probe")
    monkeypatch.setenv(variable, value)
    before = _batch_threads()

    with TestClient(app):
        assert app.state.quality_telemetry.mode is TelemetryMode.DISABLED
        assert app.state.quality_telemetry_exporter is None
        assert _batch_threads() == before


def test_a_wedged_telemetry_shutdown_does_not_hold_the_gateway_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The SDK joins its export thread for 30s; Docker's stop grace is 10s.

    Unbounded, a collector that accepts the connection and never answers turns
    an ordinary `docker compose down` into what looks like a hung container.
    """
    monkeypatch.setenv("SSF_QUALITY_TELEMETRY_MODE", "probe")
    release = threading.Event()

    class _WedgedExporter:
        def shutdown(self) -> None:
            release.wait(30)

    try:
        with TestClient(app):
            app.state.quality_telemetry_exporter.shutdown()
            monkeypatch.setattr(app.state, "quality_telemetry_exporter", _WedgedExporter())
            started = time.monotonic()
        elapsed = time.monotonic() - started
    finally:
        release.set()

    assert elapsed < 5.0, elapsed


def test_a_failing_telemetry_shutdown_is_reported_and_teardown_continues(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The exception is raised on another thread, where nothing surfaces it."""
    monkeypatch.setenv("SSF_QUALITY_TELEMETRY_MODE", "probe")

    class _BrokenExporter:
        def shutdown(self) -> None:
            raise RuntimeError("collector connection reset")

    with TestClient(app):
        app.state.quality_telemetry_exporter.shutdown()
        monkeypatch.setattr(app.state, "quality_telemetry_exporter", _BrokenExporter())

    assert "collector connection reset" in capsys.readouterr().out


def test_the_shadow_refiner_is_given_the_telemetry_the_lifespan_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refiner is a module-level singleton created at import time, while
    telemetry is built per lifespan -- so the two only meet if the lifespan
    says so. Without this the refinement event silently never fires."""
    monkeypatch.setenv("SSF_QUALITY_TELEMETRY_MODE", "enabled")

    with TestClient(app):
        assert translation_refiner.quality_telemetry is app.state.quality_telemetry


def test_the_refiner_is_released_when_the_lifespan_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale QualityTelemetry outliving its exporter would emit into a
    provider that has already been shut down."""
    monkeypatch.setenv("SSF_QUALITY_TELEMETRY_MODE", "enabled")

    with TestClient(app):
        pass

    assert translation_refiner.quality_telemetry is None
