"""The realtime series /metrics exposes, by family name and label names.

monitoring/alert_rules.yml and the ssf-overview Grafana dashboard query these
series by name and label. A renamed series or a dropped label breaks an alert
or a panel without failing anything else, so the names are pinned here after
driving the realtime surface: two sockets, a relay, a pong, polling, an HTTP
message and a refused origin.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.gateway_contract.contract_support import ALLOWED_ORIGIN

ORIGIN = {"Origin": ALLOWED_ORIGIN}
REPOSITORY = Path(__file__).resolve().parents[2]
MONITORING_FILES = (
    REPOSITORY / "monitoring" / "alert_rules.yml",
    REPOSITORY / "monitoring" / "grafana-dashboards" / "ssf-overview.json",
)
REALTIME_SERIES = re.compile(r"\b(?:websocket_|tenant_polling_)[a-z_]+")

EXPECTED_FAMILIES = {
    "websocket_broadcast_failure_total": {"sender_type", "reason"},
    "websocket_broadcast_messages_delivered_total": {"sender_type"},
    "websocket_broadcast_messages_failed_total": {"sender_type"},
    "websocket_broadcast_success_total": {"sender_type"},
    "websocket_broadcast_total": {"sender_type"},
    "websocket_connection_duration_seconds": {"client_type", "disconnect_reason"},
    "websocket_connections_active": {"client_type"},
    "websocket_connections_per_session": set(),
    "websocket_connections_total": {"client_type"},
    "websocket_disconnects_total": {"client_type", "disconnect_reason"},
    "websocket_errors_total": {"client_type"},
    "websocket_heartbeat_latency_seconds": {"client_type"},
    "websocket_message_size_bytes": {"direction", "client_type"},
    "websocket_messages_received_total": {"client_type"},
    "websocket_messages_sent_total": {"client_type"},
    "websocket_monitor_initialized": set(),
    "websocket_polling_messages_dropped_total": {"client_type"},
    "websocket_sessions_with_connections": set(),
    # An Info series is exposed with an "_info" suffix.
    "websocket_system_info_info": {"version", "monitoring_enabled", "max_connections_per_session"},
    "tenant_polling_messages_dropped_total": {"client_type"},
}

# Nothing on the realtime surface can make these count: no caller records a
# received message, a socket error needs a send that fails mid-broadcast, and
# the legacy fallback queue is unreachable from a tenant connection. Their
# label names are read from the collector the registry holds instead.
NEVER_SAMPLED = {
    "websocket_errors_total",
    "websocket_broadcast_messages_failed_total",
    "websocket_messages_received_total",
    "websocket_polling_messages_dropped_total",
}

_SAMPLE_SUFFIXES = ("_bucket", "_count", "_sum", "_created")


def _families(text: str) -> set[str]:
    return {line.split()[2] for line in text.splitlines() if line.startswith("# HELP ")}


def _family_of(sample: str, families: set[str]) -> str | None:
    if sample in families:
        return sample
    for suffix in _SAMPLE_SUFFIXES:
        if sample.endswith(suffix):
            base = sample[: -len(suffix)]
            for candidate in (base, base + "_total"):
                if candidate in families:
                    return candidate
    return None


def _sample_names(text: str) -> set[str]:
    return {
        re.split(r"[{ ]", line, maxsplit=1)[0]
        for line in text.splitlines()
        if line and not line.startswith("#")
    }


def _sampled_label_names(text: str, families: set[str]) -> dict[str, set[str]]:
    labels: dict[str, set[str]] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        sample = re.split(r"[{ ]", line, maxsplit=1)[0]
        family = _family_of(sample, families)
        if family is None:
            continue
        names = set(re.findall(r'(\w+)="', line)) - {"le"}
        labels.setdefault(family, set()).update(names)
    return labels


def _realtime(names: set[str]) -> set[str]:
    """Realtime families, without the "_created" twin a series gets once it has samples."""
    return {
        name for name in names if REALTIME_SERIES.fullmatch(name) and not name.endswith("_created")
    }


def _referenced_by_monitoring() -> set[str]:
    referenced: set[str] = set()
    for path in MONITORING_FILES:
        referenced.update(REALTIME_SERIES.findall(path.read_text(encoding="utf-8")))
    return referenced


def _frame(socket) -> dict[str, Any]:
    """The next frame that is not a heartbeat ping."""
    while True:
        frame: dict[str, Any] = socket.receive_json()
        if frame["type"] != "heartbeat_ping":
            return frame


def _settle(socket) -> None:
    """Read up to the answer to a malformed frame.

    The server answers it only after handling everything the socket sent
    before, and after every frame it had already queued for this socket.
    """
    socket.send_text("not json")
    while socket.receive_json()["type"] != "error":
        pass


def _answer_one_ping(socket) -> None:
    while True:
        frame = socket.receive_json()
        if frame["type"] == "heartbeat_ping":
            socket.send_json({"type": "heartbeat_pong", "ping_id": frame["ping_id"]})
            _settle(socket)
            return


@pytest.fixture
def local_environment(monkeypatch):
    """A development process: no Redis, no feedback database, no Studio."""
    for variable in (
        "REDIS_URL",
        "SSF_DEPLOYMENT_ENV",
        "SSF_FEEDBACK_DATABASE_URL",
        "SSF_FEEDBACK_MAINTENANCE_DATABASE_URL",
        "SSF_FEEDBACK_READER_DATABASE_URL",
    ):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("SSF_QUALITY_TELEMETRY_MODE", "disabled")


def _drive_the_realtime_surface(client, conversations, dependencies) -> None:
    dependencies.websocket_manager.heartbeat_interval = 0.05
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

            # One more relay than the poller's queue holds, so it drops one.
            for number in range(101):
                admin.send_json({"type": "message", "content": {"number": number}})
            _settle(admin)
            _answer_one_ping(customer)

            sent = client.post(
                f"/api/customer/session/{session_id}/polling/{polling_id}/send",
                json={"type": "message", "content": {"text": "from the poller"}},
            )
            assert sent.json() == {"status": "success"}
            assert conversations.send_text(session_id).status_code == 200

            customer.close()
            # The poller's envelope and the HTTP message's confirmation come first.
            while _frame(admin)["type"] != "client_left":
                pass
        admin.close()

    silent_session = conversations.create()
    conversations.activate(silent_session, "en")
    assert conversations.send_text(silent_session).status_code == 200

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/ws/customer/{session_id}", headers={"Origin": "https://evil.example"}
        ):
            pass


@pytest.mark.usefixtures("speech_services", "local_environment")
def test_metrics_exposes_the_realtime_series_by_name_and_label(client, conversations, gateway):
    # The lifespan, because it is what hands the polling store the served counter.
    with client:
        dependencies = gateway.state.dependencies
        _drive_the_realtime_surface(client, conversations, dependencies)
        response = client.get("/metrics")

    assert response.status_code == 200
    text = response.text
    families = _families(text)
    assert _realtime(families) == set(EXPECTED_FAMILIES)
    referenced = _referenced_by_monitoring()
    assert "websocket_monitor_initialized" in referenced
    assert referenced <= families | _sample_names(text), sorted(
        referenced - families - _sample_names(text)
    )

    labels = _sampled_label_names(text, families)
    registry = gateway.state.prometheus_registry
    for family, expected in EXPECTED_FAMILIES.items():
        if family in NEVER_SAMPLED and family not in labels:
            collector = registry._names_to_collectors[family]
            observed = set(collector._labelnames)
        else:
            observed = labels.get(family, set())
        assert observed == expected, family
