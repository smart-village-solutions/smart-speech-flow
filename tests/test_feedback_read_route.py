"""The HTTP contract for the Studio-facing feedback read endpoints.

Authenticated, unlike POST /api/feedback: these serve Studio staff, so the
tenant comes from the signed studio_tenant_id claim and never from the request.
"""

from datetime import datetime, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.auth import require_ssf_user
from services.api_gateway.routes.feedback import get_feedback_read_service
from services.api_gateway.tenant_context import require_studio_tenant_context

REVISION = "sha256:" + "a" * 64
TENANT = "tenant-kassel"
RECORD_ID = UUID("11111111-2222-3333-4444-555555555555")
CREATED = datetime(2026, 9, 11, 10, 30, tzinfo=timezone.utc)
EXPIRES = datetime(2027, 9, 11, 10, 30, tzinfo=timezone.utc)


def _summary(**overrides):
    from services.api_gateway.feedback.read import FeedbackSummary

    fields = {
        "feedback_id": RECORD_ID,
        "session_ref": "b" * 32,
        "translation_quality": 4,
        "performance": 5,
        "usability": 3,
        "net_promoter_score": 9,
        "has_improvements": True,
        "form_version": "v1",
        "analytics_state": "delivered",
        "created_at": CREATED,
        "expires_at": EXPIRES,
    }
    fields.update(overrides)
    return FeedbackSummary(**fields)


class StubReadService:
    def __init__(self, *, summaries=None):
        self.summaries = summaries if summaries is not None else [_summary()]
        self.listed: list = []

    async def list_for_tenant(self, *, tenant_id, accessed_by, limit, offset):
        self.listed.append((tenant_id, accessed_by, limit, offset))
        return self.summaries


@pytest.fixture
def client_for():
    def build(service) -> TestClient:
        # tests/conftest.py pins every test to tenant-test by overriding
        # require_studio_tenant_context itself. Removed here so the real
        # dependency runs and the tenant has to come from the claims below --
        # which is the behaviour these tests exist to prove.
        app.dependency_overrides.pop(require_studio_tenant_context, None)
        app.dependency_overrides[get_feedback_read_service] = lambda: service
        app.dependency_overrides[require_ssf_user] = lambda: {
            "sub": "operator-1",
            "studio_tenant_id": TENANT,
            "ssf_authorization_revision": REVISION,
        }
        return TestClient(app)

    yield build
    app.dependency_overrides.pop(get_feedback_read_service, None)
    app.dependency_overrides.pop(require_ssf_user, None)


def test_the_list_is_scoped_to_the_tenant_in_the_signed_claim(client_for) -> None:
    service = StubReadService()

    response = client_for(service).get("/api/feedback")

    assert response.status_code == 200
    assert service.listed == [(TENANT, "operator-1", 50, 0)]
    assert response.json()["items"][0]["feedback_id"] == str(RECORD_ID)


class StubDetailService(StubReadService):
    def __init__(self, *, detail=None, missing=False):
        super().__init__()
        self._detail = detail
        self._missing = missing
        self.read: list = []

    async def read_for_tenant(self, *, feedback_id, tenant_id, accessed_by):
        from services.api_gateway.feedback.read import FeedbackNotFound

        self.read.append((feedback_id, tenant_id, accessed_by))
        if self._missing:
            raise FeedbackNotFound("no such record for this tenant")
        return self._detail


def _detail(**overrides):
    from services.api_gateway.feedback.read import FeedbackDetail

    fields = {"summary": _summary(), "improvements": "More languages please."}
    fields.update(overrides)
    return FeedbackDetail(**fields)


def test_the_detail_route_discloses_the_free_text(client_for) -> None:
    service = StubDetailService(detail=_detail())

    response = client_for(service).get(f"/api/feedback/{RECORD_ID}")

    assert response.status_code == 200
    assert response.json()["improvements"] == "More languages please."
    assert service.read == [(RECORD_ID, TENANT, "operator-1")]


def test_a_record_belonging_to_another_tenant_is_not_found(client_for) -> None:
    service = StubDetailService(missing=True)

    response = client_for(service).get(f"/api/feedback/{RECORD_ID}")

    assert response.status_code == 404


def test_the_list_never_carries_free_text(client_for) -> None:
    """has_improvements reports that text exists; the text stays behind detail."""
    response = client_for(StubReadService()).get("/api/feedback")

    item = response.json()["items"][0]
    assert "improvements" not in item
    assert item["has_improvements"] is True


def test_a_tenant_selector_in_the_query_string_is_rejected(client_for) -> None:
    response = client_for(StubReadService()).get("/api/feedback?tenant_id=other-tenant")

    assert response.status_code == 400


@pytest.fixture
def unauthenticated_client():
    """No require_ssf_user override: the route must refuse on its own."""
    service = StubDetailService(detail=_detail())
    # Strip the conftest principal too, or these requests arrive authenticated.
    app.dependency_overrides.pop(require_ssf_user, None)
    app.dependency_overrides.pop(require_studio_tenant_context, None)
    app.dependency_overrides[get_feedback_read_service] = lambda: service
    yield TestClient(app)
    app.dependency_overrides.pop(get_feedback_read_service, None)


def test_listing_is_refused_without_authentication(unauthenticated_client) -> None:
    assert unauthenticated_client.get("/api/feedback").status_code in (401, 403)


def test_reading_is_refused_without_authentication(unauthenticated_client) -> None:
    response = unauthenticated_client.get(f"/api/feedback/{RECORD_ID}")

    assert response.status_code in (401, 403)
    assert "More languages" not in response.text


def test_reading_answers_503_when_the_read_role_is_unconfigured() -> None:
    """A deployment that never granted Studio read access still serves POST."""
    app.dependency_overrides[require_ssf_user] = lambda: {
        "sub": "operator-1",
        "studio_tenant_id": TENANT,
        "ssf_authorization_revision": REVISION,
    }
    try:
        response = TestClient(app).get("/api/feedback")
    finally:
        app.dependency_overrides.pop(require_ssf_user, None)

    assert response.status_code == 503


class RaisingReadService:
    """A read service whose every call fails with the given exception."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def list_for_tenant(self, **_):
        raise self._error

    async def read_for_tenant(self, **_):
        raise self._error


def test_an_undecryptable_record_is_reported_as_such(client_for) -> None:
    """A wrong or rotated key must not surface as a bare 500 with no reason."""
    from services.api_gateway.feedback.read import FeedbackTextUnreadable

    service = RaisingReadService(FeedbackTextUnreadable("did not authenticate"))

    response = client_for(service).get(f"/api/feedback/{RECORD_ID}")

    assert response.status_code == 500
    assert "decrypt" in response.json()["detail"]


@pytest.mark.parametrize("path", ["/api/feedback", f"/api/feedback/{RECORD_ID}"])
def test_an_unreachable_store_answers_a_retryable_503(client_for, path) -> None:
    from services.api_gateway.feedback.repository import FeedbackStorageUnavailable

    service = RaisingReadService(FeedbackStorageUnavailable("unreachable"))

    response = client_for(service).get(path)

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "30"
