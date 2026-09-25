"""Every family /metrics exposes, with its type, help text and label names.

Prometheus alerts and Grafana panels query the gateway's series by name and
label, and a changed help text or type is what an operator reading the scrape
sees. None of that fails anything else when it drifts, so the whole surface is
pinned here after driving a production-shaped app: Studio configured, feedback
maintenance connected, two sockets, a poller, a text and an audio message,
POST /pipeline, a rate-limited message and one pass of the audio store's
cleanup and disk usage.

The "_created" gauge prometheus_client adds beside a counter or histogram is
left out: it is derived from its family, and a labelled family only grows one
once it has a sample, which depends on the flow rather than on the code.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.gateway_contract.contract_support import ALLOWED_ORIGIN, wav_bytes

ORIGIN = {"Origin": ALLOWED_ORIGIN}
REPOSITORY = Path(__file__).resolve().parents[2]
ALERT_RULES = REPOSITORY / "monitoring" / "alert_rules.yml"
DASHBOARDS = sorted((REPOSITORY / "monitoring" / "grafana-dashboards").glob("*.json"))

Family = tuple[str, str, frozenset[str]]

EXPECTED_SURFACE: dict[str, Family] = {
    "gateway_pipeline_in_flight": (
        "gauge",
        "Pipelines currently holding an admission slot",
        frozenset(),
    ),
    "gateway_pipeline_queue_wait_seconds": (
        "histogram",
        "Time a request waited for a pipeline slot, admitted or rejected",
        frozenset(),
    ),
    "gateway_pipeline_rejected_total": (
        "counter",
        "Requests rejected with SYSTEM_BUSY because no slot came free",
        frozenset(),
    ),
    "gateway_requests_total": ("counter", "Total API Gateway requests", frozenset()),
    "refinement_attempts_total": (
        "counter",
        "Refinement attempts by outcome and model",
        frozenset({"outcome", "model_ref"}),
    ),
    "ssf_feedback_maintenance_failures_total": (
        "counter",
        "Feedback maintenance passes that could not complete",
        frozenset({"job"}),
    ),
    "ssf_feedback_reconciliation_backlog": (
        "gauge",
        "Feedback rows claimed for analytics delivery at the last pass "
        "(capped at the batch limit of 200)",
        frozenset(),
    ),
    "ssf_feedback_reconciliation_total": (
        "counter",
        "Feedback analytics reconciliation attempts by outcome",
        frozenset({"outcome"}),
    ),
    "ssf_feedback_retention_deleted_total": (
        "counter",
        "Feedback rows deleted at their retention expiry",
        frozenset(),
    ),
    "ssf_feedback_retention_overdue": (
        "gauge",
        "Feedback rows still past their retention expiry at the last pass",
        frozenset(),
    ),
    "ssf_quality_telemetry_events_total": (
        "counter",
        "Quality telemetry events by outcome",
        frozenset({"outcome"}),
    ),
    "ssf_runtime_policy_content_discarded_total": (
        "counter",
        "Conversation-content writes refused and discarded",
        frozenset({"reason"}),
    ),
    "ssf_runtime_policy_decision_total": (
        "counter",
        "Conversation-content persistence decisions",
        frozenset({"decision", "reason"}),
    ),
    "ssf_runtime_policy_read_duration_seconds": (
        "histogram",
        "Duration of one live Studio policy read",
        frozenset(),
    ),
    "tenant_polling_messages_dropped_total": (
        "counter",
        "Polling messages discarded because a bounded recipient queue was full",
        frozenset({"client_type"}),
    ),
    "websocket_broadcast_failure_total": (
        "counter",
        "Total number of failed broadcast operations",
        frozenset({"sender_type", "reason"}),
    ),
    "websocket_broadcast_messages_delivered_total": (
        "counter",
        "Total number of messages successfully delivered in broadcasts",
        frozenset({"sender_type"}),
    ),
    "websocket_broadcast_messages_failed_total": (
        "counter",
        "Total number of messages that failed to deliver in broadcasts",
        frozenset({"sender_type"}),
    ),
    "websocket_broadcast_success_total": (
        "counter",
        "Total number of successful broadcast operations",
        frozenset({"sender_type"}),
    ),
    "websocket_broadcast_total": (
        "counter",
        "Total number of broadcast operations",
        frozenset({"sender_type"}),
    ),
    "websocket_connection_duration_seconds": (
        "histogram",
        "WebSocket connection duration in seconds",
        frozenset({"client_type", "disconnect_reason"}),
    ),
    "websocket_connections_active": (
        "gauge",
        "Current number of active WebSocket connections",
        frozenset({"client_type"}),
    ),
    "websocket_connections_per_session": (
        "histogram",
        "Number of WebSocket connections per session",
        frozenset(),
    ),
    "websocket_connections_total": (
        "counter",
        "Total number of WebSocket connections established",
        frozenset({"client_type"}),
    ),
    "websocket_disconnects_total": (
        "counter",
        "Total number of WebSocket disconnections",
        frozenset({"client_type", "disconnect_reason"}),
    ),
    "websocket_errors_total": (
        "counter",
        "Total number of WebSocket errors",
        frozenset({"client_type"}),
    ),
    "websocket_heartbeat_latency_seconds": (
        "histogram",
        "WebSocket heartbeat response latency",
        frozenset({"client_type"}),
    ),
    "websocket_message_size_bytes": (
        "histogram",
        "WebSocket message size in bytes",
        frozenset({"direction", "client_type"}),
    ),
    "websocket_messages_received_total": (
        "counter",
        "Total number of messages received via WebSocket",
        frozenset({"client_type"}),
    ),
    "websocket_messages_sent_total": (
        "counter",
        "Total number of messages sent via WebSocket",
        frozenset({"client_type"}),
    ),
    "websocket_monitor_initialized": (
        "gauge",
        "WebSocket monitor initialization indicator",
        frozenset(),
    ),
    "websocket_polling_messages_dropped_total": (
        "counter",
        "Messages discarded because a polling client's queue was full",
        frozenset({"client_type"}),
    ),
    "websocket_sessions_with_connections": (
        "gauge",
        "Number of sessions with active WebSocket connections",
        frozenset(),
    ),
    # An Info series is exposed as a gauge with an "_info" suffix.
    "websocket_system_info_info": (
        "gauge",
        "WebSocket system information",
        frozenset({"version", "monitoring_enabled", "max_connections_per_session"}),
    ),
}

# Queried by monitoring/ as gateway series, and not on the gateway's /metrics.
# The audio store counts into a registry nothing serves, and the gateway's
# registry has no process collector, so these alerts and panels have no data.
# Serving them changes what production alerts on, which is its own change.
KNOWN_UNSERVED = frozenset(
    {
        "audio_cleanup_deleted_files_total",
        "audio_files_total",
        "audio_storage_disk_usage_bytes",
        "process_cpu_seconds_total",
        "process_resident_memory_bytes",
    }
)

# Series monitoring/ queries from the other scrape jobs in monitoring/prometheus.yml.
OTHER_JOBS = re.compile(
    r"^(?:DCGM_|node_|container_|otelcol_|promtail_|vllm:|asr_|translation_|tts_|up$)"
)

_PROMQL_WORDS = frozenset("""
    abs absent absent_over_time and avg avg_over_time bool bottomk by ceil changes
    clamp_max clamp_min count count_over_time delta deriv floor group_left
    group_right histogram_quantile ignoring increase irate label_replace
    last_over_time max max_over_time min min_over_time offset on or predict_linear
    quantile rate resets round scalar sort sort_desc stddev sum sum_over_time time
    topk unless vector without
    """.split())
_SAMPLE_SUFFIXES = ("_bucket", "_count", "_sum")


def _expressions() -> list[str]:
    rules = yaml.safe_load(ALERT_RULES.read_text(encoding="utf-8"))
    expressions = [rule["expr"] for group in rules["groups"] for rule in group["rules"]]

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "expr" and isinstance(value, str):
                    expressions.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for dashboard in DASHBOARDS:
        walk(json.loads(dashboard.read_text(encoding="utf-8")))
    return expressions


def _series_referenced_by_monitoring() -> set[str]:
    names: set[str] = set()
    for expression in _expressions():
        bare = re.sub(r"\{[^}]*\}|\[[^\]]*\]|\"[^\"]*\"", "", expression)
        bare = re.sub(r"\b(?:by|without|on|ignoring|group_left|group_right)\s*\([^)]*\)", "", bare)
        for token in re.findall(r"[A-Za-z_:][A-Za-z0-9_:]*", bare):
            if token not in _PROMQL_WORDS and not re.fullmatch(r"\d+[smhdwy]?", token):
                names.add(token)
    return names


def _family_of(sample: str, families: dict[str, Any]) -> str | None:
    if sample in families:
        return sample
    for suffix in _SAMPLE_SUFFIXES:
        if sample.endswith(suffix) and sample[: -len(suffix)] in families:
            return sample[: -len(suffix)]
    return None


def _is_derived_created(name: str, kinds: dict[str, str]) -> bool:
    if not name.endswith("_created"):
        return False
    base = name[: -len("_created")]
    return kinds.get(base + "_total") == "counter" or kinds.get(base) == "histogram"


def _parse(text: str) -> tuple[dict[str, str], dict[str, str], dict[str, set[str]]]:
    """HELP texts and TYPEs by family, and the label names its samples carry."""
    helps: dict[str, str] = {}
    kinds: dict[str, str] = {}
    labels: dict[str, set[str]] = {}
    for line in text.splitlines():
        if line.startswith("# HELP "):
            _, _, name, documentation = line.split(" ", 3)
            helps[name] = documentation
        elif line.startswith("# TYPE "):
            _, _, name, kind = line.split(" ", 3)
            kinds[name] = kind
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        family = _family_of(re.split(r"[{ ]", line, maxsplit=1)[0], helps)
        if family is not None:
            labels.setdefault(family, set()).update(set(re.findall(r'(\w+)="', line)) - {"le"})
    return helps, kinds, labels


def _surface(text: str, registry: Any) -> dict[str, Family]:
    helps, kinds, labels = _parse(text)
    surface: dict[str, Family] = {}
    for name, documentation in helps.items():
        if _is_derived_created(name, kinds):
            continue
        if name in labels:
            label_names = labels[name]
        else:
            # No sample to read them from: the collector registered under that name has them.
            label_names = set(registry._names_to_collectors[name]._labelnames)
        surface[name] = (kinds[name], documentation, frozenset(label_names))
    return surface


def _sample_names(text: str) -> set[str]:
    return {
        re.split(r"[{ ]", line, maxsplit=1)[0]
        for line in text.splitlines()
        if line and not line.startswith("#")
    }


class _FeedbackMaintenancePool:
    """Connects, so the lifespan wires feedback maintenance and registers its series."""

    @classmethod
    async def create(cls, *, dsn: str, password: str | None = None) -> _FeedbackMaintenancePool:
        return cls()

    async def close(self) -> None:
        return None


@pytest.fixture
def production_shaped_process(monkeypatch, tmp_path):
    """Studio configured and feedback maintenance connected; no Redis, no network."""
    from services.api_gateway.feedback import repository

    for variable in (
        "REDIS_URL",
        "SSF_DEPLOYMENT_ENV",
        "SSF_FEEDBACK_DATABASE_URL",
        "SSF_FEEDBACK_READER_DATABASE_URL",
    ):
        monkeypatch.delenv(variable, raising=False)
    # A closed port: a policy read fails at once, and is refused and counted.
    monkeypatch.setenv("STUDIO_RUNTIME_CONFIGURATION_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("STUDIO_RUNTIME_FIXED_TOKEN", "contract-fixed-token")
    monkeypatch.setenv("SSF_QUALITY_TELEMETRY_MODE", "disabled")
    monkeypatch.setenv(
        "SSF_FEEDBACK_MAINTENANCE_DATABASE_URL", "postgresql://maintenance@db.invalid/ssf"
    )
    monkeypatch.setattr(repository, "PostgresFeedbackRepository", _FeedbackMaintenancePool)
    monkeypatch.setenv("SSF_AUDIO_BASE_DIR", str(tmp_path))


def _frame(socket) -> dict[str, Any]:
    while True:
        frame: dict[str, Any] = socket.receive_json()
        if frame["type"] != "heartbeat_ping":
            return frame


def _settle(socket) -> None:
    """Read up to the answer to a malformed frame, which comes after everything queued."""
    socket.send_text("not json")
    while socket.receive_json()["type"] != "error":
        pass


def _answer_a_fresh_ping(socket) -> None:
    _settle(socket)
    frame = socket.receive_json()
    while frame["type"] != "heartbeat_ping":
        frame = socket.receive_json()
    socket.send_json({"type": "heartbeat_pong", "ping_id": frame["ping_id"]})
    _settle(socket)


def _send_audio(client, session_id: str):
    return client.post(
        f"/api/admin/session/{session_id}/message",
        files={"file": ("speech.wav", wav_bytes(), "audio/wav")},
        data={"source_lang": "de", "target_lang": "en"},
    )


def _drive_the_realtime_and_message_paths(client, conversations, dependencies) -> None:
    dependencies.websocket_manager.heartbeat_interval = 0.2
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    poller = client.post(f"/api/customer/session/{session_id}/polling/activate")
    assert poller.status_code == 200, poller.text
    polling_id = poller.json()["polling_id"]
    ticket = conversations.ticket(session_id)

    with client.websocket_connect(
        f"/ws/admin/{session_id}?ticket={ticket}", headers=ORIGIN
    ) as admin:
        assert _frame(admin)["type"] == "connection_ack"
        with client.websocket_connect(f"/ws/customer/{session_id}", headers=ORIGIN) as customer:
            assert _frame(customer)["type"] == "connection_ack"
            assert _frame(admin)["type"] == "client_joined"
            admin.send_json({"type": "message", "content": {"text": "relayed"}})
            _settle(admin)
            _answer_a_fresh_ping(customer)

            sent = client.post(
                f"/api/customer/session/{session_id}/polling/{polling_id}/send",
                json={"type": "message", "content": {"text": "from the poller"}},
            )
            assert sent.json() == {"status": "success"}
            assert conversations.send_text(session_id).status_code == 200
            assert _send_audio(client, session_id).status_code == 200

            customer.close()
            while _frame(admin)["type"] != "client_left":
                pass
        admin.close()


def _drive_the_pipeline_and_the_rate_limit(client, conversations) -> None:
    piped = client.post(
        "/pipeline",
        files={"file": ("speech.wav", wav_bytes(), "audio/wav")},
        data={"source_lang": "de", "target_lang": "en"},
    )
    assert piped.status_code == 200, piped.text

    limited_session = conversations.create()
    conversations.activate(limited_session, "en")
    statuses = [conversations.send_text(limited_session).status_code for _ in range(13)]
    assert statuses[-1] == 429, statuses


@pytest.mark.usefixtures("speech_services", "production_shaped_process")
def test_metrics_exposes_exactly_the_pinned_families(client, conversations, gateway):
    with client:
        dependencies = gateway.state.dependencies
        assert dependencies.feedback_maintenance is not None
        assert dependencies.session_manager.runtime_policy is not None
        _drive_the_realtime_and_message_paths(client, conversations, dependencies)
        _drive_the_pipeline_and_the_rate_limit(client, conversations)
        dependencies.audio_store.cleanup_expired()
        dependencies.audio_store.disk_usage()
        response = client.get("/metrics")
        registry = gateway.state.prometheus_registry

    assert response.status_code == 200
    surface = _surface(response.text, registry)
    assert set(surface) == set(EXPECTED_SURFACE), (
        sorted(set(surface) - set(EXPECTED_SURFACE)),
        sorted(set(EXPECTED_SURFACE) - set(surface)),
    )
    changed = {
        name: surface[name]
        for name, expected in EXPECTED_SURFACE.items()
        if surface[name] != expected
    }
    assert not changed, changed
    assert re.search(r"^websocket_monitor_initialized 1\.0$", response.text, re.MULTILINE)
    assert not KNOWN_UNSERVED & (set(surface) | _sample_names(response.text))


def test_every_gateway_series_monitoring_queries_is_pinned():
    served = set(EXPECTED_SURFACE)
    for name, (kind, _, _) in EXPECTED_SURFACE.items():
        if kind == "histogram":
            served.update(name + suffix for suffix in _SAMPLE_SUFFIXES)

    referenced = _series_referenced_by_monitoring()
    gateway_series = {name for name in referenced if not OTHER_JOBS.match(name)}

    assert "websocket_monitor_initialized" in gateway_series
    assert gateway_series - KNOWN_UNSERVED <= served, sorted(
        gateway_series - KNOWN_UNSERVED - served
    )
    assert KNOWN_UNSERVED <= referenced, sorted(KNOWN_UNSERVED - referenced)


_FRESH_PROCESS = """
from prometheus_client import generate_latest
from services.api_gateway.app import app
print(generate_latest(app.state.prometheus_registry).decode())
"""


def test_the_request_counter_is_exposed_at_zero_before_any_request(tmp_path):
    """The series exists from the first scrape, so increase() has a prior sample."""
    fresh = subprocess.run(
        [sys.executable, "-c", _FRESH_PROCESS],
        cwd=REPOSITORY,
        env={"PYTHONPATH": str(REPOSITORY), "SSF_AUDIO_BASE_DIR": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )

    assert re.search(r"^gateway_requests_total 0\.0$", fresh.stdout, re.MULTILINE)
