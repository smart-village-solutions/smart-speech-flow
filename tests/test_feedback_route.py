"""The HTTP contract for POST /api/feedback.

Unauthenticated by design: the customer flow carries no Keycloak identity, the
same boundary routes/customer.py sits on.
"""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.feedback.models import MAX_IMPROVEMENTS_LENGTH, FeedbackTextTooLong
from services.api_gateway.feedback.repository import FeedbackStorageUnavailable
from services.api_gateway.feedback.service import UnknownSession
from services.api_gateway.routes.feedback import get_feedback_service

ACCEPTED_ID = UUID("11111111-2222-3333-4444-555555555555")

VALID = {
    "session_id": "ABC12345",
    "translation_quality": 4,
    "performance": 5,
    "usability": 3,
    "net_promoter_score": 9,
    "improvements": "More languages please.",
    "form_version": "v1",
}


class StubService:
    def __init__(self, *, raises: Exception | None = None) -> None:
        self._raises = raises
        self.submitted: list = []

    async def submit(self, request):
        if self._raises is not None:
            raise self._raises
        self.submitted.append(request)
        return ACCEPTED_ID


@pytest.fixture
def client_for(monkeypatch):
    def build(service) -> TestClient:
        monkeypatch.setitem(app.dependency_overrides, get_feedback_service, lambda: service)
        return TestClient(app)

    return build


def test_a_valid_submission_is_created(client_for) -> None:
    client = client_for(StubService())

    response = client.post("/api/feedback", json=VALID)

    assert response.status_code == 201
    assert response.json() == {"feedback_id": str(ACCEPTED_ID)}


def test_the_route_is_registered_on_the_application() -> None:
    """A route can exist in a module and never be mounted.

    api_gateway/session.py is dead code for exactly that reason, so this
    asserts against the generated schema rather than the import.
    """
    assert "/api/feedback" in app.openapi()["paths"]
    assert "post" in app.openapi()["paths"]["/api/feedback"]


def test_an_unknown_session_is_not_found(client_for) -> None:
    client = client_for(StubService(raises=UnknownSession()))

    response = client.post("/api/feedback", json=VALID)

    assert response.status_code == 404


def test_a_storage_outage_is_retryable(client_for) -> None:
    client = client_for(StubService(raises=FeedbackStorageUnavailable("nope")))

    response = client.post("/api/feedback", json=VALID)

    assert response.status_code == 503
    assert "Retry-After" in response.headers


def test_oversize_text_is_a_client_error(client_for) -> None:
    client = client_for(StubService(raises=FeedbackTextTooLong("too long")))

    response = client.post("/api/feedback", json=VALID)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "field,value",
    [
        ("translation_quality", 9),
        ("performance", 0),
        ("usability", -1),
        ("net_promoter_score", 11),
    ],
)
def test_an_invalid_rating_is_rejected(client_for, field: str, value: int) -> None:
    client = client_for(StubService())

    response = client.post("/api/feedback", json={**VALID, field: value})

    assert response.status_code == 422


def test_a_client_supplied_tenant_is_rejected(client_for) -> None:
    """Analytical identifiers are server-owned; see tenant_context.py."""
    client = client_for(StubService())

    response = client.post("/api/feedback", json={**VALID, "tenant_id": "attacker"})

    assert response.status_code == 422


def test_a_submission_without_a_session_is_accepted(client_for) -> None:
    """Spec O1: the admin dashboard offers feedback outside any session."""
    client = client_for(StubService())

    response = client.post("/api/feedback", json={**VALID, "session_id": None})

    assert response.status_code == 201


def test_the_endpoint_requires_no_authentication(client_for) -> None:
    """The customer has no Keycloak identity; requiring one would lose them."""
    client = client_for(StubService())

    response = client.post("/api/feedback", json=VALID)

    assert response.status_code != 401
    assert response.status_code != 403


def test_an_unconfigured_feedback_store_reports_unavailable(monkeypatch) -> None:
    """Feedback must degrade, never take the gateway down with it.

    The gateway serves the whole conversation pipeline; an unreachable or
    unconfigured feedback database must cost submissions a retryable 503, not
    cost every customer their session.
    """
    monkeypatch.delitem(app.dependency_overrides, get_feedback_service, raising=False)
    monkeypatch.setattr(app.state, "feedback_service", None, raising=False)
    response = TestClient(app).post("/api/feedback", json=VALID)

    assert response.status_code == 503
    assert "Retry-After" in response.headers


def test_an_oversize_text_error_does_not_echo_the_text(client_for) -> None:
    client = client_for(StubService(raises=FeedbackTextTooLong("too long")))
    sentinel = "SENTINEL-PURPLE-RHINOCEROS"
    payload = {**VALID, "improvements": sentinel + "x" * MAX_IMPROVEMENTS_LENGTH}

    response = client.post("/api/feedback", json=payload)

    assert response.status_code == 422
    assert sentinel not in response.text


def test_a_storage_error_response_does_not_echo_the_text(client_for) -> None:
    client = client_for(StubService(raises=FeedbackStorageUnavailable("nope")))
    sentinel = "SENTINEL-PURPLE-RHINOCEROS"

    response = client.post("/api/feedback", json={**VALID, "improvements": sentinel})

    assert response.status_code == 503
    assert sentinel not in response.text


def test_a_rating_error_response_does_not_echo_the_text(client_for) -> None:
    """FastAPI copies errors() into the 422 body, `input` included."""
    client = client_for(StubService())
    sentinel = "SENTINEL-PURPLE-RHINOCEROS"
    payload = {**VALID, "usability": 99, "improvements": sentinel}

    response = client.post("/api/feedback", json=payload)

    assert response.status_code == 422
    assert sentinel not in response.text


def test_a_session_id_no_session_could_carry_answers_404(client_for) -> None:
    """Not a 500, which is what it was.

    A real FeedbackService rather than the stub, because the defect lived in
    the seam between them: the store raises ValueError on an id outside
    ^[A-Za-z0-9_-]{1,128}$, and this route catches UnknownSession,
    FeedbackTextTooLong and FeedbackStorageUnavailable -- none of which that
    is. The repository, cipher and telemetry are never reached, so the
    submission is refused before anything would use them.
    """
    from services.api_gateway.feedback.service import FeedbackService
    from services.api_gateway.feedback.tenant import ConfiguredTenantResolver
    from services.api_gateway.session_manager import SessionManager
    from services.api_gateway.session_store import RedisTenantSessionStore

    class EmptyRedis:
        def get(self, key):
            return None

    service = FeedbackService(
        repository=None,
        cipher=None,
        tenant_resolver=ConfiguredTenantResolver(tenant_id="tenant-a"),
        session_manager=SessionManager(store=RedisTenantSessionStore(EmptyRedis())),
        telemetry=None,
    )
    client = client_for(service)

    response = client.post("/api/feedback", json={**VALID, "session_id": "a b"})

    assert response.status_code == 404
    assert response.json()["detail"] == "The session is not known"
