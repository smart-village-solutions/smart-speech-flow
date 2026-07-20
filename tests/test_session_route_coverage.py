"""Behavioral coverage for session state and the session-facing routes."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services.api_gateway import session as legacy_session_routes
from services.api_gateway.routes import customer, session as session_routes
from services.api_gateway.session_manager import (
    ClientType,
    Session,
    SessionMessage,
    SessionStatus,
    session_manager,
)


@pytest.fixture(autouse=True)
def reset_session_manager():
    """Keep singleton-backed route state isolated between behavioral tests."""
    session_manager.reset(clear_persistence=True)
    session_manager.allow_parallel_sessions = False
    yield
    session_manager.reset(clear_persistence=True)


def test_session_round_trip_keeps_message_and_timeout_state():
    created_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    message = SessionMessage(
        id="message-1",
        sender=ClientType.CUSTOMER,
        original_text="Hello",
        translated_text="Hallo",
        audio_base64=None,
        source_lang="en",
        target_lang="de",
        timestamp=created_at,
        pipeline_metadata={"steps": [{"name": "translation"}]},
        original_audio_url="/api/audio/input_message-1.wav",
    )
    session = Session(
        id="SESSION1",
        customer_language="en",
        status=SessionStatus.ACTIVE,
        created_at=created_at,
        last_activity=created_at,
        messages=[message],
        timeout_warning_sent=True,
    )

    restored = Session.from_dict(session.to_dict(include_messages=True))

    assert restored.status is SessionStatus.ACTIVE
    assert restored.messages[0].sender is ClientType.CUSTOMER
    assert restored.messages[0].pipeline_metadata == {"steps": [{"name": "translation"}]}
    assert restored.messages[0].original_audio_url.endswith("message-1.wav")
    assert restored.timeout_warning_sent is True
    assert restored.to_dict()["minutes_since_activity"] >= 1


@pytest.mark.asyncio
async def test_manager_replaces_previous_active_session_and_rejects_terminated_updates():
    first_id = await session_manager.create_admin_session()
    second_id = await session_manager.create_admin_session()

    first = session_manager.get_session(first_id)
    assert first.status is SessionStatus.TERMINATED
    assert first.termination_reason == "new_session_created"
    assert session_manager.get_active_session()["id"] == second_id

    await session_manager.terminate_session(second_id, "manual_termination")
    with pytest.raises(ValueError, match="beendet"):
        await session_manager.activate_session(second_id, "en")


@pytest.mark.asyncio
async def test_legacy_session_routes_create_list_messages_and_reject_unknown_language():
    created = await legacy_session_routes.create_session("en")

    assert created["status"] == "created"
    assert created["admin_url"].endswith(created["session_id"])

    info = await legacy_session_routes.get_session_info(created["session_id"])
    active = await legacy_session_routes.get_active_sessions()
    messages = await legacy_session_routes.get_session_messages(created["session_id"])

    assert info["customer_language"] == "en"
    assert info["status"] is SessionStatus.ACTIVE
    assert active["sessions"][0]["id"] == created["session_id"]
    assert messages == {"session_id": created["session_id"], "messages": []}

    with pytest.raises(HTTPException) as raised:
        await legacy_session_routes.create_session("xx")
    assert raised.value.status_code == 400


@pytest.mark.asyncio
async def test_session_routes_report_missing_session_and_unsupported_content_type():
    with pytest.raises(HTTPException) as missing:
        await session_routes.get_session_info("MISSING")
    assert missing.value.status_code == 404

    session_id = session_manager.create_session("en")
    request = SimpleNamespace(headers={"content-type": "text/plain"})

    with pytest.raises(HTTPException) as unsupported:
        await session_routes.send_unified_message(session_id, request)
    assert unsupported.value.status_code == 400
    assert unsupported.value.detail["error_code"] == "UNSUPPORTED_CONTENT_TYPE"


@pytest.mark.asyncio
async def test_activity_route_requires_active_session_and_connections():
    session_id = await session_manager.create_admin_session()
    manager = SimpleNamespace(get_session_connections=lambda _: {})

    inactive_update = session_routes.update_client_activity(
        session_id, session_routes.ClientActivityUpdate(), manager
    )
    with pytest.raises(HTTPException) as inactive:
        await inactive_update
    assert inactive.value.status_code == 400

    await session_manager.activate_session(session_id, "en")
    disconnected_update = session_routes.update_client_activity(
        session_id, session_routes.ClientActivityUpdate(), manager
    )
    with pytest.raises(HTTPException) as disconnected:
        await disconnected_update
    assert disconnected.value.status_code == 400


@pytest.mark.asyncio
async def test_customer_activation_updates_pending_session_and_status_response():
    session_id = await session_manager.create_admin_session()
    request = customer.ActivateSessionRequest(
        session_id=session_id, customer_language="ar"
    )

    activation = await customer.activate_session(request)
    status = await customer.get_customer_session_status(session_id)

    assert activation.status == "active"
    assert activation.customer_language == "ar"
    assert status["is_active"] is True
    assert status["can_send_messages"] is True
    assert status["customer_connected"] is True


@pytest.mark.asyncio
async def test_customer_routes_return_expected_errors_for_missing_and_terminated_sessions():
    missing_request = customer.ActivateSessionRequest(
        session_id="MISSING", customer_language="en"
    )
    with pytest.raises(HTTPException) as missing:
        await customer.activate_session(missing_request)
    assert missing.value.status_code == 404

    session_id = await session_manager.create_admin_session()
    await session_manager.terminate_session(session_id)
    terminated_request = customer.ActivateSessionRequest(
        session_id=session_id, customer_language="en"
    )
    with pytest.raises(HTTPException) as terminated:
        await customer.activate_session(terminated_request)
    assert terminated.value.status_code == 400

    with pytest.raises(HTTPException) as unknown_status:
        await customer.get_customer_session_status("MISSING")
    assert unknown_status.value.status_code == 404
