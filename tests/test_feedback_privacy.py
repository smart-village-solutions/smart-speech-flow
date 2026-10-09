"""Free text must not reach logs, telemetry, or responses.

Every test here uses one sentinel string and asserts its absence. If a test in
this file ever needs relaxing, that is a design change, not a test fix.

Each of these has been watched failing against a deliberately leaky
implementation; a guard that has never rejected anything is not evidence.
"""

import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry

from services.api_gateway.app import app
from services.api_gateway.feedback.crypto import FeedbackCipher
from services.api_gateway.feedback.forms import FeedbackForms
from services.api_gateway.feedback.models import MAX_IMPROVEMENTS_LENGTH
from services.api_gateway.feedback.repository import FeedbackStorageUnavailable
from services.api_gateway.feedback.service import FeedbackService
from services.api_gateway.feedback.tenant import ConfiguredTenantResolver
from services.api_gateway.routes.feedback import get_feedback_service
from services.api_gateway.session_pseudonym import SessionPseudonymizer
from services.api_gateway.studio_content import StudioContentCache
from services.api_gateway.studio_content_metrics import StudioContentMetrics
from services.api_gateway.studio_content_service import StudioContentService
from services.api_gateway.studio_runtime_v2_client import StudioRuntimeV2ClientError
from services.api_gateway.studio_v2 import parse_runtime_configuration_v2

SENTINEL = "PURPLE-RHINOCEROS-9317-SENTINEL"
KASSEL = "tenant-kassel"
REVISION = "sha256:" + "a" * 64
FIXTURE = Path(__file__).parent / "fixtures" / "studio_v2" / "runtime-tenant-kassel.json"

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
        from services.api_gateway.quality_telemetry_schema import ProbeOutcome, ProbeResult

        self.calls.append(kwargs)
        return ProbeResult(ProbeOutcome.EMITTED, kwargs.get("event_id"))


class KnownSessions:
    """A legacy session: known by its bare id, with no tenant key behind it."""

    def has_unscoped_session(self, session_id):
        return True

    async def resolve_customer_session(self, session_id):
        return None

    async def resolve_ended_session(self, session_id, *, within):
        return None


class FakeStudio:
    """Kassel's captured configuration, or a Studio that is down."""

    def __init__(self, down: bool = False) -> None:
        self.down = down

    async def fetch(self, *arguments):
        if self.down:
            raise StudioRuntimeV2ClientError("studio_runtime_network_error", retryable=True)
        body = json.loads(FIXTURE.read_text(encoding="utf-8"))
        body["configurationRevision"] = REVISION
        return parse_runtime_configuration_v2(body, expected_tenant_id=KASSEL)


def _assemble(repository=None, *, studio_down: bool = False):
    repository = repository if repository is not None else RecordingRepository()
    telemetry = RecordingTelemetry()
    content = StudioContentService(
        StudioContentCache(),
        runtime=FakeStudio(down=studio_down),
        installation=None,
        metrics=StudioContentMetrics(CollectorRegistry()),
    )
    service = FeedbackService(
        repository=repository,
        cipher=FeedbackCipher(key=b"0" * 32),
        # Kassel, so the guest form comes from Kassel's Studio content.
        tenant_resolver=ConfiguredTenantResolver(tenant_id=KASSEL),
        session_manager=KnownSessions(),
        telemetry=telemetry,
        pseudonymizer=SessionPseudonymizer(key=b"feedback-privacy-test"),
        forms=FeedbackForms(content),
    )
    app.dependency_overrides[get_feedback_service] = lambda: service
    return TestClient(app), repository, telemetry


@pytest.fixture
def assembled():
    client, repository, telemetry = _assemble()
    yield client, repository, telemetry
    app.dependency_overrides.pop(get_feedback_service, None)


@pytest.fixture
def studio_down():
    client, repository, telemetry = _assemble(studio_down=True)
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
    assert SENTINEL.encode("utf-8") not in record.text_answers_ciphertext
    assert SENTINEL not in str(record.consent_snapshot)
    assert SENTINEL not in str(record.numeric_answers)
    assert SENTINEL not in str(record.form_snapshot)


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


V2 = {
    "audience": "guest",
    "session_id": "ABC12345",
    "locale": "en",
    "form_source": "studio",
    "configuration_revision": REVISION,
    "answers": {
        "translationQuality": 4,
        "performance": 5,
        "usability": 3,
        "recommendation": 9,
        "improvementIdeas": f"The translator said {SENTINEL} to me.",
    },
}


def _answers(**changes: object) -> dict:
    return {**V2, "answers": {**V2["answers"], **changes}}


def _without(body: dict, field: str) -> dict:
    return {key: value for key, value in body.items() if key != field}


def _assert_nothing_leaks(response, caplog: pytest.LogCaptureFixture) -> None:
    assert SENTINEL not in response.text
    assert SENTINEL not in caplog.text


@pytest.mark.parametrize(
    "body",
    [
        _without(VALID, "usability"),
        {**_without(VALID, "translation_quality"), "usability": 99},
        _without(V2, "locale"),
        _without(V2, "form_source"),
        {**V2, "audience": "visitor"},
        {**V2, "tenant_id": "tenant-b"},
        {**VALID, "audience": "guest"},
    ],
    ids=[
        "v1-missing-field",
        "v1-missing-and-invalid",
        "v2-missing-locale",
        "v2-missing-source",
        "v2-unknown-audience",
        "v2-extra-field",
        "v1-fields-under-an-audience",
    ],
)
def test_no_422_echoes_the_body(assembled, caplog: pytest.LogCaptureFixture, body: dict) -> None:
    """FastAPI's 422 puts the whole body in `input` for a missing field."""
    client, repository, _ = assembled

    with caplog.at_level(logging.DEBUG):
        response = client.post("/api/feedback", json=body)

    assert response.status_code == 422
    _assert_nothing_leaks(response, caplog)
    assert repository.stored == []


@pytest.mark.parametrize(
    "body",
    [
        _answers(improvementIdeas=SENTINEL * 400),
        _answers(**{SENTINEL: 3}),
        _answers(usability=SENTINEL),
        _answers(recommendation=f"{SENTINEL} 9"),
        {**V2, "answers": SENTINEL},
        {**V2, "answers": [SENTINEL]},
    ],
    ids=["too-long", "unknown-key", "text-as-rating", "text-as-scale", "string", "list"],
)
def test_no_409_echoes_an_answer(assembled, caplog: pytest.LogCaptureFixture, body: dict) -> None:
    client, repository, telemetry = assembled

    with caplog.at_level(logging.DEBUG):
        response = client.post("/api/feedback", json=body)

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "feedback_form_changed"
    _assert_nothing_leaks(response, caplog)
    assert repository.stored == []
    assert telemetry.calls == []


def test_a_coded_422_echoes_nothing(assembled, caplog: pytest.LogCaptureFixture) -> None:
    client, _, _ = assembled

    with caplog.at_level(logging.DEBUG):
        response = client.post("/api/feedback", json={**V2, "session_id": None})

    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "feedback_request_invalid"
    _assert_nothing_leaks(response, caplog)


def test_studio_down_echoes_nothing(studio_down, caplog: pytest.LogCaptureFixture) -> None:
    client, repository, _ = studio_down

    with caplog.at_level(logging.DEBUG):
        response = client.post("/api/feedback", json=V2)

    assert response.status_code == 503
    assert response.json()["detail"]["error_code"] == "feedback_form_unavailable"
    _assert_nothing_leaks(response, caplog)
    assert repository.stored == []


def test_a_v2_storage_failure_echoes_nothing(failing, caplog: pytest.LogCaptureFixture) -> None:
    client, _, _ = failing

    with caplog.at_level(logging.DEBUG):
        response = client.post("/api/feedback", json=V2)

    assert response.status_code == 503
    _assert_nothing_leaks(response, caplog)


def test_an_accepted_v2_submission_leaks_nothing(
    assembled, caplog: pytest.LogCaptureFixture
) -> None:
    client, repository, telemetry = assembled

    with caplog.at_level(logging.DEBUG):
        response = client.post("/api/feedback", json=V2)

    assert response.status_code == 201
    _assert_nothing_leaks(response, caplog)
    record = repository.stored[0]
    assert SENTINEL.encode("utf-8") not in record.text_answers_ciphertext
    assert SENTINEL not in str(telemetry.calls)
