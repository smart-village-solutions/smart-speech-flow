import asyncio
import logging
import traceback
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services.api_gateway import app as app_module
from services.api_gateway.routes import customer
from services.api_gateway.session_manager import SessionStatus


class SensitiveRouteError(RuntimeError):
    pass


def test_customer_exception_log_keeps_traceback_without_sensitive_message(
    monkeypatch, caplog
):
    session_id = "private-session-id"
    language = "private-language"
    exception_text = "private-exception-text"
    request = customer.ActivateSessionRequest(
        session_id=session_id,
        customer_language=language,
    )

    def fail_session_lookup(_session_id):
        raise SensitiveRouteError(exception_text)

    monkeypatch.setattr(customer.session_manager, "get_session", fail_session_lookup)

    with caplog.at_level(logging.ERROR, logger=customer.logger.name):
        activation = customer.activate_session(request)
        with pytest.raises(HTTPException) as raised:
            asyncio.run(activation)

    assert raised.value.status_code == 500
    exception_records = [record for record in caplog.records if record.exc_info]
    assert len(exception_records) == 1
    record = exception_records[0]
    assert record.exc_info[2] is not None
    assert any(
        frame.name == "fail_session_lookup"
        for frame in traceback.extract_tb(record.exc_info[2])
    )
    assert session_id not in caplog.text
    assert language not in caplog.text
    assert exception_text not in caplog.text


def test_unsupported_customer_language_warning_omits_tainted_value(
    monkeypatch, caplog
):
    language = "tainted-language-value"
    session = SimpleNamespace(status=SessionStatus.PENDING)
    monkeypatch.setattr(customer.session_manager, "get_session", lambda _session_id: session)

    async def activate_session(_session_id, _language):
        return None

    monkeypatch.setattr(customer.session_manager, "activate_session", activate_session)
    request = customer.ActivateSessionRequest(
        session_id="session-id",
        customer_language=language,
    )

    with caplog.at_level(logging.WARNING, logger=customer.logger.name):
        response = asyncio.run(customer.activate_session(request))

    assert response.customer_language == language
    warning_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING
    ]
    assert warning_messages == ["⚠️ Nicht unterstützte Kundensprache angefordert"]
    assert all(language not in message for message in warning_messages)


def test_health_path_constant_preserves_service_health_urls():
    assert app_module.HEALTH_PATH == "/health"
    assert all(
        service_url.endswith(app_module.HEALTH_PATH)
        for service_url in app_module.SERVICE_URLS.values()
    )
