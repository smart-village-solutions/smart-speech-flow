"""POST /api/admin/feedback: staff feedback, filed under the token's tenant."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.auth import require_ssf_user
from services.api_gateway.feedback.answers import FeedbackFormChanged
from services.api_gateway.feedback.models import FeedbackSubmissionV2
from services.api_gateway.routes.feedback import get_feedback_service
from services.api_gateway.studio_runtime_flow import (
    ValidatedRuntimeConfiguration,
    require_validated_runtime_configuration,
)
from services.api_gateway.tenant_context import StudioTenantContext, require_studio_tenant_context
from tests.gateway_contract.contract_support import runtime_read

ROUTE = "/api/admin/feedback"
REVISION = f"sha256:{'a' * 64}"
ACCEPTED_ID = UUID("11111111-2222-3333-4444-555555555555")
SENTINEL = "PURPLE-RHINOCEROS-9317-SENTINEL"
BODY = {
    "audience": "staff",
    "locale": "de-DE",
    "form_source": "studio",
    "configuration_revision": REVISION,
    "answers": {"translationQuality": 4, "improvementIdeas": SENTINEL},
}


class StubService:
    def __init__(self, raises: Exception | None = None) -> None:
        self.raises = raises
        self.staff: list = []

    async def submit_staff(self, submission, *, tenant_id, correlation_id):
        if self.raises is not None:
            raise self.raises
        self.staff.append((submission, tenant_id))
        return ACCEPTED_ID


@pytest.fixture
def service() -> StubService:
    return StubService()


@pytest.fixture
def client(service: StubService) -> Iterator[TestClient]:
    original = app.dependency_overrides.copy()
    with TestClient(app) as test_client:
        app.dependency_overrides[get_feedback_service] = lambda: service
        yield test_client
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original)


def _as(tenant: str, subject: str) -> None:
    context = StudioTenantContext(tenant, REVISION)
    configuration = runtime_read(tenant)
    app.dependency_overrides[require_ssf_user] = lambda: {"sub": subject}
    app.dependency_overrides[require_studio_tenant_context] = lambda: context
    app.dependency_overrides[require_validated_runtime_configuration] = lambda: (
        ValidatedRuntimeConfiguration(context, configuration, "test-correlation")
    )


def _session(client: TestClient, tenant: str, subject: str) -> str:
    _as(tenant, subject)
    response = client.post("/api/admin/session/create")
    assert response.status_code == 201
    return response.json()["session_id"]


def test_staff_feedback_is_filed_under_the_tokens_tenant(client, service) -> None:
    _as("tenant-a", "admin-1")

    response = client.post(ROUTE, json=BODY)

    assert response.status_code == 201
    assert response.json() == {"feedback_id": str(ACCEPTED_ID)}
    ((submission, tenant_id),) = service.staff
    assert isinstance(submission, FeedbackSubmissionV2)
    assert tenant_id == "tenant-a"


def test_feedback_about_an_own_session_is_accepted(client, service) -> None:
    session_id = _session(client, "tenant-a", "admin-1")

    response = client.post(ROUTE, json={**BODY, "session_id": session_id})

    assert response.status_code == 201
    assert service.staff[0][0].session_id == session_id


def test_a_session_of_another_tenant_is_not_found(client, service) -> None:
    session_id = _session(client, "tenant-b", "admin-1")
    _as("tenant-a", "admin-1")

    response = client.post(ROUTE, json={**BODY, "session_id": session_id})

    assert response.status_code == 404
    assert response.json() == {"detail": "Session not found"}
    assert service.staff == []


def test_a_colleagues_session_is_not_found(client, service) -> None:
    session_id = _session(client, "tenant-a", "admin-1")
    _as("tenant-a", "admin-2")

    response = client.post(ROUTE, json={**BODY, "session_id": session_id})

    assert response.status_code == 404
    assert service.staff == []


def test_an_unknown_session_is_not_found(client, service) -> None:
    _as("tenant-a", "admin-1")

    response = client.post(ROUTE, json={**BODY, "session_id": "NOSUCH99"})

    assert response.status_code == 404


def test_a_tenant_in_the_body_is_refused(client, service) -> None:
    _as("tenant-a", "admin-1")

    response = client.post(ROUTE, json={**BODY, "tenant_id": "tenant-b"})

    assert response.status_code == 422
    assert service.staff == []


def test_a_v1_body_is_refused(client, service) -> None:
    _as("tenant-a", "admin-1")
    v1 = {
        "translation_quality": 4,
        "performance": 5,
        "usability": 3,
        "net_promoter_score": 9,
        "improvements": SENTINEL,
    }

    response = client.post(ROUTE, json=v1)

    assert response.status_code == 422
    assert SENTINEL not in response.text


def test_a_conflict_carries_no_answer(client) -> None:
    app.dependency_overrides[get_feedback_service] = lambda: StubService(
        FeedbackFormChanged("too_long")
    )
    _as("tenant-a", "admin-1")

    response = client.post(ROUTE, json=BODY)

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "feedback_form_changed"
    assert SENTINEL not in response.text


def test_a_missing_field_does_not_echo_the_answers(client) -> None:
    _as("tenant-a", "admin-1")
    body = {key: value for key, value in BODY.items() if key != "locale"}

    response = client.post(ROUTE, json=body)

    assert response.status_code == 422
    assert SENTINEL not in response.text


def test_the_route_requires_a_staff_token(client) -> None:
    app.dependency_overrides.pop(require_ssf_user, None)
    app.dependency_overrides.pop(require_studio_tenant_context, None)

    response = client.post(ROUTE, json=BODY)

    assert response.status_code == 401


def test_feedback_about_an_own_ended_session_is_accepted(client, service) -> None:
    """The sheet stays open while the conversation ends; its feedback must not be lost."""
    session_id = _session(client, "tenant-a", "admin-1")
    assert client.delete(f"/api/admin/session/{session_id}/terminate").status_code == 200

    response = client.post(ROUTE, json={**BODY, "session_id": session_id})

    assert response.status_code == 201
    assert service.staff[0][0].session_id == session_id
