import asyncio
import logging
import traceback
from types import SimpleNamespace

import pytest
from fastapi import Request

from services.api_gateway import service_urls
from services.api_gateway import session_lifecycle
from services.api_gateway.routes import admin, customer
from services.api_gateway.session_lifecycle import SessionLifecycleService
from services.api_gateway.session_models import SessionStatus
from services.api_gateway.tenant_context import StudioTenantContext
from services.api_gateway.tenant_session import TenantSessionKey


class SensitiveRouteError(RuntimeError):
    pass


def _http_request() -> Request:
    """A minimal ASGI request; the route reads only its correlation header."""
    return Request({"type": "http", "headers": []})


@pytest.mark.asyncio
async def test_admin_history_leaves_an_unexpected_error_to_the_unhandled_error_net(
    session_manager, monkeypatch, caplog
):
    exception_text = "private-history-exception"
    context = StudioTenantContext(
        tenant_id="tenant-test",
        authorization_revision=f"sha256:{'a' * 64}",
    )
    monkeypatch.setattr(
        session_manager,
        "get_session_history",
        lambda **_kwargs: (_ for _ in ()).throw(SensitiveRouteError(exception_text)),
    )

    with caplog.at_level(logging.ERROR, logger=admin.logger.name):
        with pytest.raises(SensitiveRouteError):
            await admin.get_session_history(
                context, SessionLifecycleService(session_manager), "owner-ref"
            )

    # The route neither reshapes nor logs it: the unhandled-error middleware answers
    # the JSON 500 and the redacted log (tests/test_unhandled_error_middleware.py).
    assert exception_text not in caplog.text


def test_customer_activation_leaves_an_unexpected_error_to_the_unhandled_error_net(
    session_manager, monkeypatch, caplog
):
    session_id = "private-session-id"
    language = "private-language"
    exception_text = "private-exception-text"
    request = customer.ActivateSessionRequest(
        session_id=session_id,
        customer_language=language,
    )
    key = TenantSessionKey("tenant-test", session_id)

    def fail_session_lookup(_session_id):
        raise SensitiveRouteError(exception_text)

    monkeypatch.setattr(customer, "require_customer_session_key", lambda *_args: key)
    monkeypatch.setattr(session_manager, "get_session", fail_session_lookup)

    with caplog.at_level(logging.ERROR, logger=customer.logger.name):
        activation = customer.activate_session(
            request,
            _http_request(),
            None,
            session_manager,
            None,
            SessionLifecycleService(session_manager),
        )
        with pytest.raises(SensitiveRouteError) as raised:
            asyncio.run(activation)

    assert any(
        frame.name == "fail_session_lookup" for frame in traceback.extract_tb(raised.tb)
    )
    assert [record for record in caplog.records if record.exc_info] == []
    assert session_id not in caplog.text
    assert language not in caplog.text
    assert exception_text not in caplog.text


def test_unsupported_customer_language_warning_omits_tainted_value(
    session_manager, monkeypatch, caplog
):
    language = "tainted-language-value"
    session = SimpleNamespace(status=SessionStatus.PENDING)
    key = TenantSessionKey("tenant-test", "session-id")
    monkeypatch.setattr(customer, "require_customer_session_key", lambda *_args: key)
    monkeypatch.setattr(session_manager, "get_session", lambda _session_id: session)

    async def activate_session(_session_id, _language):
        return None

    monkeypatch.setattr(session_manager, "activate_session", activate_session)
    request = customer.ActivateSessionRequest(
        session_id="session-id",
        customer_language=language,
    )

    with caplog.at_level(logging.WARNING, logger=session_lifecycle.logger.name):
        response = asyncio.run(
            customer.activate_session(
                request,
                _http_request(),
                None,
                session_manager,
                None,
                SessionLifecycleService(session_manager),
            )
        )

    assert response.customer_language == language
    warning_messages = [
        record.getMessage() for record in caplog.records if record.levelno == logging.WARNING
    ]
    assert warning_messages == ["⚠️ Nicht unterstützte Kundensprache angefordert"]
    assert all(language not in message for message in warning_messages)


def test_health_path_constant_preserves_service_health_urls():
    assert service_urls.HEALTH_PATH == "/health"
    assert all(
        service_url.endswith(service_urls.HEALTH_PATH)
        for service_url in service_urls.SERVICE_URLS.values()
    )
