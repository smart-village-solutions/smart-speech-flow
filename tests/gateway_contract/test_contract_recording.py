"""Recording a live conversation over the real routes and sockets (spec §5.1, §5.2)."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from services.api_gateway.app import app
from services.api_gateway.auth import require_ssf_user
from services.api_gateway.clock import utc_now
from services.api_gateway.recording.audit import AuditEvent
from services.api_gateway.recording.session_service import RecordingSessions
from services.api_gateway.recording.wiring import WebSocketAnnouncer
from services.api_gateway.studio_v2 import RecordingPolicy
from services.api_gateway.tenant_session import TenantSessionKey
from tests.gateway_contract.contract_support import ALLOWED_ORIGIN, TENANT_A, wav_bytes
from tests.guest_access import open_guest_socket
from tests.recording_archive_fakes import archive_rig, open_object

ORIGIN = {"Origin": ALLOWED_ORIGIN}
STATE_KEYS = {
    "type",
    "session_id",
    "state",
    "reason",
    "window_id",
    "state_version",
    "since",
    "role",
}
POLICY = RecordingPolicy.model_validate(
    {
        "enabled": True,
        "legalBasis": "consent",
        "signature": "optional",
        "idCheck": "off",
        "retentionHours": 720,
        "verificationRequired": False,
        "recoveryMode": "standard",
        "timestampAuthorityUrl": "https://tsa.example.org/tsr",
        "auditRetentionHours": 8760,
    }
)


@pytest.fixture
def recording(gateway_dependencies, identity, tmp_path):
    audit: list[AuditEvent] = []
    rig = archive_rig(tmp_path, utc_now)

    async def policy(_tenant_id: str) -> RecordingPolicy:
        return POLICY

    async def recovery_key_ready(_tenant_id: str) -> bool:
        return True

    async def append(event: AuditEvent) -> None:
        audit.append(event)

    sessions = RecordingSessions(
        store=gateway_dependencies.recording_state_store,
        announcer=WebSocketAnnouncer(gateway_dependencies.websocket_manager),
        policy=policy,
        recovery_key_ready=recovery_key_ready,
        audit=append,
        archive=rig.archive,
    )
    sessions.rig = rig  # type: ignore[attr-defined]
    gateway_dependencies.recording_sessions = sessions
    gateway_dependencies.websocket_manager.recording = sessions
    gateway_dependencies.session_manager.recording = sessions
    app.dependency_overrides[require_ssf_user] = lambda: identity.claims() | {
        "ssf_permissions": ["ssf.recording.request"]
    }
    return sessions


def _admin_socket(client, conversations, session_id: str):
    ticket = conversations.ticket(session_id)
    return client.websocket_connect(f"/ws/admin/{session_id}?ticket={ticket}", headers=ORIGIN)


def _queued(socket) -> list[dict[str, Any]]:
    """Every frame already queued on `socket`, read up to the answer to a malformed frame."""
    socket.send_text("not json")
    frames: list[dict[str, Any]] = []
    while True:
        frame: dict[str, Any] = socket.receive_json()
        if frame["type"] == "error":
            return frames
        frames.append(frame)


def _of(frames: list[dict[str, Any]], frame_type: str) -> list[dict[str, Any]]:
    return [frame for frame in frames if frame["type"] == frame_type]


def _ack(socket, version: int) -> None:
    socket.send_json({"type": "recording_state_ack", "state_version": version})


def test_a_recording_is_asked_answered_acknowledged_and_stopped(
    client, conversations, recording
) -> None:
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    request_id = str(uuid.uuid4())
    with _admin_socket(client, conversations, session_id) as admin:
        with open_guest_socket(client, session_id, ORIGIN) as guest:
            greeted = _of(_queued(guest), "recording_state")
            assert [frame["state"] for frame in greeted] == ["off"]
            assert set(greeted[0]) == STATE_KEYS
            _queued(admin)

            asked = client.post(
                f"/api/admin/session/{session_id}/recording/request",
                json={"request_id": request_id},
            )
            assert asked.status_code == 200, asked.text
            assert asked.json()["state"] == "asking"
            guest_frames = _queued(guest)
            assert [frame["type"] for frame in guest_frames] == [
                "recording_state",
                "recording_request",
            ]
            assert guest_frames[1] == {
                "type": "recording_request",
                "session_id": session_id,
                "request_id": request_id,
                "consent_kind": "first",
                "role": "recording_request",
            }
            assert [frame["state"] for frame in _queued(admin)] == ["asking"]

            answered = client.post(
                f"/api/customer/session/{session_id}/recording/answer",
                json={"request_id": request_id, "consent": True},
            )
            assert answered.status_code == 200, answered.text
            arming = answered.json()
            assert (arming["state"], bool(arming["window_id"])) == ("arming", True)
            for socket in (admin, guest):
                frames = _queued(socket)
                assert [frame["type"] for frame in frames] == ["recording_state", "recording_ping"]
                socket.send_json({"type": "recording_pong"})

            _ack(admin, arming["state_version"])
            _ack(guest, arming["state_version"])
            for socket in (admin, guest):
                (on,) = _of(_queued(socket), "recording_state")
                assert (on["state"], on["window_id"]) == ("on", arming["window_id"])
            _ack(admin, on["state_version"])
            _ack(guest, on["state_version"])
            assert _of(_queued(admin), "recording_state") == []
            assert _of(_queued(guest), "recording_state") == []
            assert recording.live(TenantSessionKey(TENANT_A, session_id))
            snapshot = client.portal.call(
                recording.snapshot, TenantSessionKey(TENANT_A, session_id)
            )
            assert snapshot.holds()

            stopped = client.post(f"/api/customer/session/{session_id}/recording/stop")
            assert (stopped.json()["state"], stopped.json()["reason"]) == (
                "off",
                "stopped_by_guest",
            )
            assert [frame["state"] for frame in _of(_queued(admin), "recording_state")] == ["off"]


def test_only_a_permitted_employee_may_ask(client, conversations, recording, identity) -> None:
    session_id = conversations.create()
    app.dependency_overrides[require_ssf_user] = identity.claims
    state = client.get(f"/api/admin/session/{session_id}/recording")
    assert state.json() | {"since": None} == {
        "state": "off",
        "reason": None,
        "window_id": None,
        "state_version": 0,
        "since": None,
        "can_request": False,
        "unavailable_reason": "PERMISSION_REQUIRED",
    }
    refused = client.post(
        f"/api/admin/session/{session_id}/recording/request",
        json={"request_id": str(uuid.uuid4())},
    )
    assert (refused.status_code, refused.json()["detail"]["error_code"]) == (
        403,
        "PERMISSION_REQUIRED",
    )


def test_a_request_needs_the_guest_on_a_socket(client, conversations, recording) -> None:
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    refused = client.post(
        f"/api/admin/session/{session_id}/recording/request",
        json={"request_id": str(uuid.uuid4())},
    )
    assert (refused.status_code, refused.json()["detail"]["error_code"]) == (
        409,
        "GUEST_NOT_CONNECTED",
    )


def test_without_recording_wired_the_routes_answer_503(client, conversations) -> None:
    session_id = conversations.create()
    response = client.get(f"/api/admin/session/{session_id}/recording")
    assert (response.status_code, response.json()["detail"]["error_code"]) == (
        503,
        "RECORDING_UNAVAILABLE",
    )


def test_another_admins_session_is_not_found(client, conversations, recording, identity) -> None:
    session_id = conversations.create()
    app.dependency_overrides[require_ssf_user] = lambda: identity.claims() | {
        "sub": "someone-else",
        "ssf_permissions": ["ssf.recording.request"],
    }
    response = client.post(f"/api/admin/session/{session_id}/recording/stop")
    assert response.status_code == 404


def test_the_session_end_turns_recording_off(client, conversations, recording) -> None:
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    with open_guest_socket(client, session_id, ORIGIN) as guest:
        _queued(guest)
        asked = client.post(
            f"/api/admin/session/{session_id}/recording/request",
            json={"request_id": str(uuid.uuid4())},
        )
        assert asked.json()["state"] == "asking"
    conversations.terminate(session_id)
    state = client.portal.call(recording.state, TenantSessionKey(TENANT_A, session_id))
    assert (state.phase.value, state.reason.value) == ("off", "session_ended")


def _recording_on(client, conversations, session_id, admin, guest) -> None:
    request_id = str(uuid.uuid4())
    _queued(admin)
    _queued(guest)
    client.post(
        f"/api/admin/session/{session_id}/recording/request", json={"request_id": request_id}
    )
    armed = client.post(
        f"/api/customer/session/{session_id}/recording/answer",
        json={"request_id": request_id, "consent": True},
    ).json()
    for socket in (admin, guest):
        _queued(socket)
        _ack(socket, armed["state_version"])
    for socket in (admin, guest):
        (on,) = _of(_queued(socket), "recording_state")
    for socket in (admin, guest):
        _ack(socket, on["state_version"])
        _queued(socket)


def test_a_closed_guest_socket_ends_liveness_at_once(client, conversations, recording) -> None:
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    key = TenantSessionKey(TENANT_A, session_id)
    with _admin_socket(client, conversations, session_id) as admin:
        with open_guest_socket(client, session_id, ORIGIN) as guest:
            _recording_on(client, conversations, session_id, admin, guest)
            assert client.portal.call(recording.snapshot, key).holds()
            guest.close()
            # The socket is released before its peers hear `client_left`.
            while admin.receive_json()["type"] != "client_left":
                pass
            assert not client.portal.call(recording.snapshot, key).holds()


def test_a_failed_greeting_leaves_the_socket_working(client, conversations, recording) -> None:
    session_id = conversations.create()

    store = recording._store
    load = store.load

    async def broken_once(key):
        store.load = load
        raise RuntimeError("redis hiccup")

    store.load = broken_once
    with _admin_socket(client, conversations, session_id) as admin:
        assert admin.receive_json()["type"] == "connection_ack"
        assert _queued(admin) == []
    conversations.terminate(session_id)


@pytest.mark.parametrize("token", [None, "not-the-guests-token"])
def test_only_the_sessions_guest_may_answer_or_stop(client, conversations, recording, token):
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    headers = {} if token is None else {"X-Guest-Token": token}
    client.guest_tokens.pop(session_id)
    answered = client.post(
        f"/api/customer/session/{session_id}/recording/answer",
        json={"request_id": str(uuid.uuid4()), "consent": True},
        headers=headers,
    )
    stopped = client.post(f"/api/customer/session/{session_id}/recording/stop", headers=headers)
    assert (answered.status_code, stopped.status_code) == (409, 409)


def _turn_on(client, conversations, session_id: str, admin, guest) -> None:
    """Ask, answer yes, and acknowledge through ARMING and ON on both sockets."""
    _queued(admin), _queued(guest)
    request_id = str(uuid.uuid4())
    client.post(
        f"/api/admin/session/{session_id}/recording/request", json={"request_id": request_id}
    )
    arming = client.post(
        f"/api/customer/session/{session_id}/recording/answer",
        json={"request_id": request_id, "consent": True},
    ).json()
    for socket in (admin, guest):
        _queued(socket)
        socket.send_json({"type": "recording_pong"})
        _ack(socket, arming["state_version"])
    for socket in (admin, guest):
        (on,) = _of(_queued(socket), "recording_state")
        assert on["state"] == "on"
    for socket in (admin, guest):
        _ack(socket, on["state_version"])
        _queued(socket)


def _entries(recording) -> list[Any]:
    return [entry for chain in recording.rig.repository.entries.values() for entry in chain]


def _kinds(recording) -> list[str]:
    return [entry.kind for entry in _entries(recording)]


def test_messages_are_archived_only_while_recording_and_playback_is_reported(
    client, conversations, recording, speech_services
) -> None:
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    with _admin_socket(client, conversations, session_id) as admin:
        with open_guest_socket(client, session_id, ORIGIN) as guest:
            _turn_on(client, conversations, session_id, admin, guest)

            sent = client.post(
                f"/api/admin/session/{session_id}/message",
                files={"file": ("speech.wav", wav_bytes(), "audio/wav")},
                data={"source_lang": "de", "target_lang": "en"},
            )
            assert sent.status_code == 200, sent.text
            assert _kinds(recording) == ["consent", "message"]

            played = client.post(
                f"/api/customer/session/{session_id}/recording/playback",
                json={"message_id": sent.json()["message_id"], "event": "completed"},
            )
            assert played.status_code == 204
            assert _kinds(recording) == ["consent", "message", "playback"]
            playback = json.loads(
                client.portal.call(
                    open_object, recording.rig, _entries(recording)[-1], "playback.json"
                )
            )
            assert (playback["reported_by"], playback["event"]) == ("customer", "completed")

            speech_services.fail("translation", 500)
            assert conversations.send_text(session_id).status_code >= 400
            assert _kinds(recording)[-1] == "failed"
            spoken = client.post(
                f"/api/admin/session/{session_id}/message",
                files={"file": ("speech.wav", wav_bytes(), "audio/wav")},
                data={"source_lang": "de", "target_lang": "en"},
            )
            assert spoken.status_code >= 400
            failed_audio = _entries(recording)[-1]
            assert failed_audio.kind == "failed"
            assert "original.wav" in failed_audio.objects
            speech_services.recover("translation")

            client.post(f"/api/admin/session/{session_id}/recording/stop")
            assert conversations.send_text(session_id).status_code == 200
            assert _kinds(recording) == ["consent", "message", "playback", "failed", "failed"]


def test_a_playback_report_with_a_malformed_body_is_refused(client, conversations, recording):
    session_id = conversations.create()
    refused = client.post(
        f"/api/admin/session/{session_id}/recording/playback",
        json={"message_id": "not-a-uuid", "event": "completed"},
    )
    assert refused.status_code == 422
