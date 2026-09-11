"""Free text must not reach logs, telemetry, or responses.

Every test here uses one sentinel string and asserts its absence. If a test in
this file ever needs relaxing, that is a design change, not a test fix.

Each of these has been watched failing against a deliberately leaky
implementation; a guard that has never rejected anything is not evidence.
"""

import logging

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.feedback.crypto import FeedbackCipher
from services.api_gateway.feedback.models import MAX_IMPROVEMENTS_LENGTH
from services.api_gateway.feedback.repository import FeedbackStorageUnavailable
from services.api_gateway.feedback.service import FeedbackService
from services.api_gateway.feedback.tenant import ConfiguredTenantResolver
from services.api_gateway.routes.feedback import get_feedback_service

SENTINEL = "PURPLE-RHINOCEROS-9317-SENTINEL"

VALID = {
    "session_id": "ABC12345",
    "translation_quality": 4,
    "performance": 5,
    "usability": 3,
    "net_promoter_score": 9,
    "improvements": f"The translator said {SENTINEL} to me.",
    "form_version": "v1",
}


class RecordingRepository:
    def __init__(self) -> None:
        self.stored: list = []

    async def store(self, record) -> None:
        self.stored.append(record)

    async def mark_analytics_delivered(self, feedback_id, tenant_id) -> None: ...

    async def mark_analytics_state(self, feedback_id, state, tenant_id) -> None: ...

    async def claim_pending_analytics(self, limit):
        return []

    async def delete_expired(self, now, limit):
        return []


class FailingRepository(RecordingRepository):
    async def store(self, record) -> None:
        raise FeedbackStorageUnavailable("the feedback record could not be committed")


class RecordingTelemetry:
    def __init__(self) -> None:
        self.calls: list = []

    def emit_feedback_submitted(self, **kwargs):
        from services.api_gateway.quality_telemetry import ProbeOutcome, ProbeResult

        self.calls.append(kwargs)
        return ProbeResult(ProbeOutcome.EMITTED, kwargs.get("event_id"))


class KnownSessions:
    def get_session(self, session_id):
        from types import SimpleNamespace

        return SimpleNamespace(id=session_id)


def _assemble(repository=None):
    repository = repository if repository is not None else RecordingRepository()
    telemetry = RecordingTelemetry()
    service = FeedbackService(
        repository=repository,
        cipher=FeedbackCipher(key=b"0" * 32),
        tenant_resolver=ConfiguredTenantResolver(tenant_id="tenant-a"),
        session_manager=KnownSessions(),
        telemetry=telemetry,
    )
    app.dependency_overrides[get_feedback_service] = lambda: service
    return TestClient(app), repository, telemetry


@pytest.fixture
def assembled():
    client, repository, telemetry = _assemble()
    yield client, repository, telemetry
    app.dependency_overrides.pop(get_feedback_service, None)


@pytest.fixture
def failing():
    client, repository, telemetry = _assemble(FailingRepository())
    yield client, repository, telemetry
    app.dependency_overrides.pop(get_feedback_service, None)


def test_the_stored_row_holds_no_plaintext(assembled) -> None:
    client, repository, _ = assembled

    client.post("/api/feedback", json=VALID)

    record = repository.stored[0]
    assert SENTINEL.encode("utf-8") not in record.improvements_ciphertext
    assert SENTINEL not in str(record.consent_snapshot)


def test_telemetry_attributes_hold_no_plaintext(assembled) -> None:
    client, _, telemetry = assembled

    client.post("/api/feedback", json=VALID)

    assert telemetry.calls
    assert SENTINEL not in str(telemetry.calls)


def test_telemetry_attributes_hold_no_raw_session_id(assembled) -> None:
    client, _, telemetry = assembled

    client.post("/api/feedback", json=VALID)

    assert "ABC12345" not in str(telemetry.calls)


def test_the_success_response_holds_no_plaintext(assembled) -> None:
    client, _, _ = assembled

    response = client.post("/api/feedback", json=VALID)

    assert response.status_code == 201
    assert SENTINEL not in response.text


def test_no_log_record_holds_the_plaintext(assembled, caplog: pytest.LogCaptureFixture) -> None:
    client, _, _ = assembled

    with caplog.at_level(logging.DEBUG):
        client.post("/api/feedback", json=VALID)

    assert SENTINEL not in caplog.text


def test_a_storage_failure_leaks_nothing(failing, caplog: pytest.LogCaptureFixture) -> None:
    """The failure path is where a naive handler logs the request body."""
    client, _, _ = failing

    with caplog.at_level(logging.DEBUG):
        response = client.post("/api/feedback", json=VALID)

    assert response.status_code == 503
    assert SENTINEL not in caplog.text
    assert SENTINEL not in response.text


def test_an_oversize_submission_leaks_nothing(assembled, caplog: pytest.LogCaptureFixture) -> None:
    """The single most likely leak: an error that quotes what was rejected."""
    client, _, _ = assembled
    payload = {**VALID, "improvements": SENTINEL + "x" * MAX_IMPROVEMENTS_LENGTH}

    with caplog.at_level(logging.DEBUG):
        response = client.post("/api/feedback", json=payload)

    assert response.status_code == 422
    assert SENTINEL not in response.text
    assert SENTINEL not in caplog.text


def test_an_invalid_rating_does_not_echo_the_text(
    assembled, caplog: pytest.LogCaptureFixture
) -> None:
    """FastAPI copies errors() into the 422 body, each error's `input` too."""
    client, _, _ = assembled

    with caplog.at_level(logging.DEBUG):
        response = client.post("/api/feedback", json={**VALID, "usability": 99})

    assert response.status_code == 422
    assert SENTINEL not in response.text
    assert SENTINEL not in caplog.text
