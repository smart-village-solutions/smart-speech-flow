"""Regression tests for the internal ClickHouse Compose security contract."""


def test_clickhouse_service_is_internal_and_persistent(rendered_development_compose: dict) -> None:
    """Fail if ClickHouse becomes public or loses durable storage."""
    service = rendered_development_compose["services"]["clickhouse"]

    assert service["image"] == "clickhouse/clickhouse-server:26.3.17.110"
    assert service["restart"] == "always"
    assert service.get("ports") is None
    assert service["expose"] == ["8123"]
    assert {
        "type": "volume",
        "source": "clickhouse-data",
        "target": "/var/lib/clickhouse",
        "volume": {},
    } in service["volumes"]
    assert service.get("labels") is None


def test_clickhouse_service_receives_required_credentials(rendered_development_compose: dict) -> None:
    """Fail if resolved ClickHouse credentials are omitted from the service."""
    environment = rendered_development_compose["services"]["clickhouse"]["environment"]

    assert environment["CLICKHOUSE_PASSWORD"] == "test-only-password"
    assert environment["CLICKHOUSE_USER"] == "ssf_telemetry_test"
    assert environment["CLICKHOUSE_DB"] == "ssf_analytics_test"
