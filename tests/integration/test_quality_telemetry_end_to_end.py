"""Requires a running clickhouse + otel-collector. Not part of the default run.

The emission goes through the gateway's own lifespan-built telemetry inside the
gateway container, so this covers env parsing, the emitter, the allowlist and
the shipped OTLP adapter. Hand-building an exporter here would skip all four --
and did, which is how a wrong exporter signature stayed invisible.
"""

import json
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from services.api_gateway.quality_telemetry import ALLOWED_ATTRIBUTE_KEYS

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[2]
COLLECTOR_IMAGE = "otel/opentelemetry-collector-contrib:0.159.0"
_ALLOWED_RESOURCE_KEYS = {
    "service.name",
    "service.version",
    "deployment.environment.name",
}

_EMIT_THROUGH_LIFESPAN = """
import asyncio, json
from services.api_gateway.app import app, lifespan

async def main():
    async with lifespan(app):
        results = [
            app.state.quality_telemetry.emit_probe(event_type="telemetry_probe")
            for _ in range(EMISSIONS)
        ]
    print("RESULT " + json.dumps(
        [{"outcome": r.outcome.value, "event_id": str(r.event_id)} for r in results]
    ))

asyncio.run(main())
"""


def _query(sql: str) -> str:
    return subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "clickhouse",
            "sh",
            "-ec",
            f'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" '
            f'--database "$CLICKHOUSE_DB" --query "{sql}"',
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _emit_through_the_gateway(emissions: int = 1) -> list[dict]:
    """Run the gateway's real startup path and emit, then let teardown flush."""
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "-e",
            "SSF_QUALITY_TELEMETRY_MODE=probe",
            "-e",
            "SSF_RELEASE_VERSION=itest",
            "-e",
            "SSF_DEPLOYMENT_ENV=itest",
            "api_gateway",
            "python",
            "-c",
            _EMIT_THROUGH_LIFESPAN.replace("EMISSIONS", str(emissions)),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    line = next(ln for ln in completed.stdout.splitlines() if ln.startswith("RESULT "))
    return json.loads(line[len("RESULT ") :])


def _await_silver(event_id: str, expected: str = "1") -> None:
    for _ in range(30):
        count = _query(
            f"SELECT count() FROM quality_events FINAL " f"WHERE event_id = toUUID('{event_id}')"
        )
        if count == expected:
            return
        time.sleep(1)
    pytest.fail(f"probe event {event_id} never reached quality_events")


def test_a_probe_emitted_through_the_gateway_reaches_the_silver_table() -> None:
    (result,) = _emit_through_the_gateway()
    assert result["outcome"] == "emitted", result

    _await_silver(result["event_id"])

    row = _query(
        f"SELECT event_type, service_name, service_version, deployment_env, "
        f"schema_version FROM quality_events FINAL "
        f"WHERE event_id = toUUID('{result['event_id']}')"
    )
    # service_version proves this came from the gateway's own lifespan, which
    # reads SSF_RELEASE_VERSION, rather than from a test-built exporter.
    assert row.split("\t") == ["telemetry_probe", "api_gateway", "itest", "itest", "1"]


def test_only_allowlisted_fields_survive_the_collector() -> None:
    """The privacy claim in the runbook, checked against what actually landed."""
    (result,) = _emit_through_the_gateway()
    _await_silver(result["event_id"])

    # length(Body) rather than Body: an empty leading field would be stripped.
    body_length, log_keys, resource_keys = _query(
        f"SELECT length(Body), arraySort(mapKeys(LogAttributes)), "
        f"arraySort(mapKeys(ResourceAttributes)) FROM otel_logs "
        f"WHERE LogAttributes['ssf.quality.event_id'] = '{result['event_id']}'"
    ).split("\t")

    assert body_length == "0"
    assert set(json.loads(log_keys.replace("'", '"'))) == set(ALLOWED_ATTRIBUTE_KEYS)
    assert set(json.loads(resource_keys.replace("'", '"'))) == _ALLOWED_RESOURCE_KEYS


def test_the_event_timestamp_is_the_gateways_emission_time() -> None:
    """Not the collector's observation time: silver's column is named for it."""
    (result,) = _emit_through_the_gateway()
    _await_silver(result["event_id"])

    drift_seconds = _query(
        f"SELECT abs(dateDiff('second', emitted_at_utc, ingested_at_utc)) "
        f"FROM quality_events FINAL WHERE event_id = toUUID('{result['event_id']}')"
    )
    assert int(drift_seconds) < 60, drift_seconds


def test_duplicate_delivery_is_counted_once() -> None:
    """Two bronze rows for one event id must collapse to one silver row."""
    event_id = str(uuid.uuid4())
    for _ in range(2):
        subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "clickhouse",
                "sh",
                "-ec",
                'clickhouse-client --user "$CLICKHOUSE_USER" '
                '--password "$CLICKHOUSE_PASSWORD" --database "$CLICKHOUSE_DB" '
                '--query "INSERT INTO otel_logs (Timestamp, ServiceName, Body, '
                "ResourceAttributes, ScopeName, LogAttributes, EventName) VALUES "
                "(now64(9), 'api_gateway', '', "
                "{'service.version': 'itest', 'deployment.environment.name': 'itest'}, "
                f"'ssf.quality', {{'ssf.quality.event_id': '{event_id}', "
                "'ssf.quality.schema_version': '1'}, 'telemetry_probe')\"",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

    _await_silver(event_id)
    assert (
        _query(
            f"SELECT count() FROM quality_events FINAL " f"WHERE event_id = toUUID('{event_id}')"
        )
        == "1"
    )


def test_the_collector_config_is_valid_for_the_pinned_image() -> None:
    """Catches OTTL typos and unknown components, which YAML parsing cannot."""
    completed = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{ROOT / 'monitoring' / 'otel-collector-config.yaml'}:/cfg.yaml:ro",
            "-e",
            "CLICKHOUSE_DB=db",
            "-e",
            "CLICKHOUSE_USER=u",
            "-e",
            "CLICKHOUSE_PASSWORD=p",
            "--entrypoint",
            "/otelcol-contrib",
            COLLECTOR_IMAGE,
            "validate",
            "--config=file:/cfg.yaml",
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


_RAW_OTLP_POST = """
import json, time, urllib.request
payload = {"resourceLogs": [{
    "resource": {"attributes": [
        {"key": "service.name", "value": {"stringValue": "api_gateway"}},
        {"key": "service.version", "value": {"stringValue": "itest"}},
        {"key": "deployment.environment.name", "value": {"stringValue": "itest"}},
        {"key": "ssf.leaked.source_text", "value": {"stringValue": "SECRET"}},
        {"key": "net.peer.ip", "value": {"stringValue": "10.1.2.3"}},
    ]},
    "scopeLogs": [{"scope": {"name": "ssf.quality"}, "logRecords": [{
        "timeUnixNano": str(time.time_ns()),
        "body": {"stringValue": "LEAKED BODY TEXT"},
        "eventName": "telemetry_probe",
        "attributes": [
            {"key": "ssf.quality.event_id", "value": {"stringValue": "EVENT_ID"}},
            {"key": "ssf.quality.schema_version", "value": {"stringValue": "1"}},
            {"key": "ssf.quality.source_text", "value": {"stringValue": "SECRET"}},
        ],
    }]}],
}]}
request = urllib.request.Request(
    "http://otel-collector:4318/v1/logs",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(request, timeout=10) as response:
    print("STATUS", response.status)
"""


def test_the_collector_strips_content_a_rogue_sender_supplies() -> None:
    """The second line of defence, on its own.

    The gateway's Resource(attributes=...) is what keeps un-allowlisted fields
    off the wire today, so nothing else here exercises the collector's own
    filtering. This posts raw OTLP carrying a body and content-bearing log and
    resource attributes, and asserts none of it is stored.
    """
    event_id = str(uuid.uuid4())
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "api_gateway",
            "python",
            "-c",
            _RAW_OTLP_POST.replace("EVENT_ID", event_id),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "STATUS 200" in completed.stdout, completed.stdout

    _await_silver(event_id)

    body_length, log_keys, resource_keys = _query(
        f"SELECT length(Body), arraySort(mapKeys(LogAttributes)), "
        f"arraySort(mapKeys(ResourceAttributes)) FROM otel_logs "
        f"WHERE LogAttributes['ssf.quality.event_id'] = '{event_id}'"
    ).split("\t")

    assert body_length == "0"
    assert set(json.loads(log_keys.replace("'", '"'))) == set(ALLOWED_ATTRIBUTE_KEYS)
    assert set(json.loads(resource_keys.replace("'", '"'))) == _ALLOWED_RESOURCE_KEYS


def test_the_collector_drops_a_record_that_is_not_a_quality_event() -> None:
    """Fail closed: a non-quality log must be dropped, not silently rewritten."""
    before = _query("SELECT count() FROM otel_logs")
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "api_gateway",
            "python",
            "-c",
            _RAW_OTLP_POST.replace(
                '{"key": "ssf.quality.event_id", "value": {"stringValue": "EVENT_ID"}},',
                "",
            ),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "STATUS 200" in completed.stdout, completed.stdout

    time.sleep(10)
    assert _query("SELECT count() FROM otel_logs") == before
