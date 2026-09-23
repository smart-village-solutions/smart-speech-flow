"""Token-safe classification of rejected administrative bearer tokens."""

import logging
import re

import pytest
from fastapi import FastAPI
from prometheus_client import CollectorRegistry
from starlette.requests import Request

from services.api_gateway.auth_rejections import (
    AuthRejectionMetrics,
    AuthRejectionReason,
    auth_correlation_id,
    record_auth_rejection,
    rejection_response,
    rejection_status,
)
from services.api_gateway.session_pseudonym import tenant_ref

AUTH_LOGGER = "services.api_gateway.auth_rejections"
UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def _request(headers=None, app=None):
    raw = [
        (name.lower().encode("latin-1"), value.encode("latin-1"))
        for name, value in (headers or {}).items()
    ]
    return Request(
        {"type": "http", "method": "GET", "path": "/", "headers": raw, "app": app or FastAPI()}
    )


def test_reason_codes_are_a_closed_snake_case_set():
    values = [reason.value for reason in AuthRejectionReason]
    assert all(re.fullmatch(r"[a-z_]+", value) for value in values)
    assert len(set(values)) == len(values)


@pytest.mark.parametrize("reason", list(AuthRejectionReason))
def test_responses_keep_the_existing_neutral_bodies(reason):
    response = rejection_response(reason)
    assert response.status_code == rejection_status(reason)
    if reason is AuthRejectionReason.DIRECTORY_UNAVAILABLE:
        assert (response.status_code, response.detail, response.headers) == (
            503,
            "The login directory is temporarily unavailable",
            None,
        )
    elif reason is AuthRejectionReason.ROLE_MISSING:
        assert (response.status_code, response.detail, response.headers) == (
            403,
            "The bearer token lacks the required role",
            None,
        )
    else:
        assert (response.status_code, response.detail, response.headers) == (
            401,
            "A valid bearer token is required",
            {"WWW-Authenticate": "Bearer"},
        )


@pytest.mark.parametrize("value", ["req-1.a:b_c", "has space", "x" * 128])
def test_a_valid_correlation_id_is_kept(value):
    assert auth_correlation_id(_request({"X-Correlation-Id": value})) == value


@pytest.mark.parametrize("value", ["", "x" * 129, "tab\there", "caf\xe9"])
def test_an_invalid_correlation_id_is_replaced_without_raising(value):
    assert UUID_PATTERN.fullmatch(auth_correlation_id(_request({"X-Correlation-Id": value})))


def test_a_missing_correlation_id_is_generated():
    assert UUID_PATTERN.fullmatch(auth_correlation_id(_request()))


def test_rejection_logs_one_line_with_only_safe_fields(caplog):
    caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)
    record_auth_rejection(
        _request(),
        AuthRejectionReason.REVISION_MISSING,
        correlation_id="corr-1",
        tenant_id="tenant-kassel",
    )
    [record] = caplog.records
    assert record.getMessage() == (
        "ssf_auth_rejected reason=revision_missing status=401 "
        f"tenant_ref={tenant_ref('tenant-kassel')} correlation_id=corr-1"
    )
    assert "tenant-kassel" not in record.getMessage()
    assert (record.reason, record.status, record.correlation_id) == (
        "revision_missing",
        401,
        "corr-1",
    )


def test_rejection_without_a_tenant_logs_a_placeholder_ref(caplog):
    caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)
    record_auth_rejection(_request(), AuthRejectionReason.MISSING_BEARER, correlation_id="c")
    assert "tenant_ref=- " in caplog.records[0].getMessage()


def test_metrics_count_by_reason_when_bound_to_the_app():
    registry = CollectorRegistry()
    app = FastAPI()
    app.state.auth_rejection_metrics = AuthRejectionMetrics(registry)
    record_auth_rejection(_request(app=app), AuthRejectionReason.ROLE_MISSING, correlation_id="c")

    def value(reason):
        return registry.get_sample_value("gateway_auth_rejections_total", {"reason": reason})

    assert value("role_missing") == 1
    assert all(
        value(reason.value) == 0 for reason in AuthRejectionReason if reason.value != "role_missing"
    )


def test_the_gateway_serves_the_rejection_counter():
    from fastapi.testclient import TestClient

    from services.api_gateway.app import app

    response = TestClient(app).get("/metrics")

    assert response.status_code == 200
    assert 'gateway_auth_rejections_total{reason="revision_missing"}' in response.text


def test_the_gateway_counts_a_real_rejection(monkeypatch):
    from fastapi.testclient import TestClient

    from services.api_gateway.app import app
    from services.api_gateway.auth import require_ssf_user

    # tests/conftest.py bypasses authentication outside test_auth.py.
    monkeypatch.delitem(app.dependency_overrides, require_ssf_user)

    def missing_bearer_count():
        return app.state.prometheus_registry.get_sample_value(
            "gateway_auth_rejections_total", {"reason": "missing_bearer"}
        )

    before = missing_bearer_count()
    assert TestClient(app).get("/api/admin/session/history").status_code == 401
    assert missing_bearer_count() == before + 1


def test_recording_without_bound_metrics_only_logs(caplog):
    caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)
    record_auth_rejection(_request(), AuthRejectionReason.UNKNOWN_ISSUER, correlation_id="c")
    assert [record.reason for record in caplog.records] == ["unknown_issuer"]
