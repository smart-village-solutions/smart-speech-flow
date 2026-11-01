"""Recording a live conversation over the real routes and sockets (spec §5.1, §5.2)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from services.api_gateway.app import app
from services.api_gateway.auth import require_ssf_user
from services.api_gateway.clock import utc_now
from services.api_gateway.recording.audit import AuditEvent
from services.api_gateway.recording.consent_text import consent_text
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
        pseudonymizer=gateway_dependencies.session_manager.pseudonymizer,
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


def _yes(client, session_id: str, request_id: str) -> dict[str, Any]:
    """A yes as the guest's screen sends it: the hash of the text it was served, and a name."""
    served = client.get(f"/api/customer/session/{session_id}/recording/consent")
    assert served.status_code == 200, served.text
    digest = hashlib.sha256(served.json()["html"].encode()).hexdigest()
    return {"request_id": request_id, "consent": True, "text_sha256": digest, "name": "Amira"}


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
                json=_yes(client, session_id, request_id),
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
        "staff_release": None,
        "next_consent_kind": "first",
        "id_check": None,
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
        json=_yes(client, session_id, request_id),
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
        json=_yes(client, session_id, request_id),
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


def test_a_busy_pipeline_is_not_archived_as_a_failure(
    client, conversations, recording, speech_services
) -> None:
    # Like a busy rejection at admission: the speaker sends it again, nothing failed.
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    with _admin_socket(client, conversations, session_id) as admin:
        with open_guest_socket(client, session_id, ORIGIN) as guest:
            _turn_on(client, conversations, session_id, admin, guest)
            speech_services.fail("translation", 503, headers={"Retry-After": "7"})

            typed = conversations.send_text(session_id)
            spoken = client.post(
                f"/api/admin/session/{session_id}/message",
                files={"file": ("speech.wav", wav_bytes(), "audio/wav")},
                data={"source_lang": "de", "target_lang": "en"},
            )

            assert (typed.status_code, spoken.status_code) == (503, 503)
            assert _kinds(recording) == ["consent"]
            assert not recording.rig.repository.incomplete


def test_a_playback_report_with_a_malformed_body_is_refused(client, conversations, recording):
    session_id = conversations.create()
    refused = client.post(
        f"/api/admin/session/{session_id}/recording/playback",
        json={"message_id": "not-a-uuid", "event": "completed"},
    )
    assert refused.status_code == 422


PNG = b"\x89PNG\r\n\x1a\n" + b"\x02" * 16


class _Voice:
    """The TTS service as the read-aloud route sees it."""

    def __init__(self) -> None:
        self.fails = False
        # TTS answers 200 with a JSON body when synthesis fails.
        self.content_type = "audio/wav"
        self.payloads: list[dict[str, Any]] = []

    def synthesize(self, payload: dict[str, Any], *, timeout: float) -> Any:
        self.payloads.append(payload)
        if self.fails:
            raise ConnectionError("tts down")
        return SimpleNamespace(
            status_code=200, headers={"content-type": self.content_type}, content=b"RIFF-read-aloud"
        )


def _ask(client, session_id: str, **extras: Any) -> str:
    request_id = str(uuid.uuid4())
    asked = client.post(
        f"/api/admin/session/{session_id}/recording/request",
        json={"request_id": request_id, **extras},
    )
    assert asked.status_code == 200, asked.text
    return request_id


def _error(response) -> tuple[int, str]:
    return response.status_code, response.json()["detail"]["error_code"]


def test_the_guest_answers_with_the_hash_of_the_text_it_was_served(
    client, conversations, recording, monkeypatch
) -> None:
    monkeypatch.setitem(globals(), "POLICY", POLICY.model_copy(update={"id_check": "optional"}))
    session_id = conversations.create()
    conversations.activate(session_id, "ar")
    with open_guest_socket(client, session_id, ORIGIN):
        request_id = _ask(client, session_id, guest_name=" Amira ", id_checked=True)
        served = client.get(f"/api/customer/session/{session_id}/recording/consent").json()
        assert served == {
            "request_id": request_id,
            "consent_kind": "first",
            "language": "ar",
            "html": consent_text(POLICY, "ar", "first").html,
            "text_sha256": consent_text(POLICY, "ar", "first").answer_sha256,
            "accept_label": None,
            "decline_label": None,
            "documentation_consent": None,
            "signature": "optional",
            "proposed_name": "Amira",
        }
        answer = f"/api/customer/session/{session_id}/recording/answer"
        tampered = _yes(client, session_id, request_id) | {"text_sha256": "0" * 64}
        assert _error(client.post(answer, json=tampered)) == (409, "CONSENT_TEXT_MISMATCH")

        signed = _yes(client, session_id, request_id) | {
            "signature_png": base64.b64encode(PNG).decode()
        }
        answered = client.post(answer, json=signed)
        assert answered.status_code == 200, answered.text

    [consent] = _entries(recording)
    record = json.loads(asyncio.run(open_object(recording.rig, consent, "consent.json")))
    assert record["guest"] == {"name": "Amira", "entered_by": "employee"}
    assert record["signature"]["given"] is True
    assert record["id_check"]["checked"] is True
    assert (record["text"]["language"], record["text_de"]["language"]) == ("ar", "de")


def test_without_an_open_question_there_is_no_consent_text(client, conversations, recording):
    session_id = conversations.create()
    served = client.get(f"/api/customer/session/{session_id}/recording/consent")
    assert _error(served) == (409, "RECORDING_REQUEST_STALE")


def test_a_signature_that_is_not_a_png_is_refused(client, conversations, recording) -> None:
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    with open_guest_socket(client, session_id, ORIGIN):
        request_id = _ask(client, session_id)
        body = _yes(client, session_id, request_id) | {"signature_png": "R0lGODlh"}
        refused = client.post(f"/api/customer/session/{session_id}/recording/answer", json=body)
    assert _error(refused) == (422, "INVALID_SIGNATURE")


def test_a_required_id_check_is_offered_to_and_enforced_on_the_employee(
    client, conversations, recording, monkeypatch
) -> None:
    monkeypatch.setitem(globals(), "POLICY", POLICY.model_copy(update={"id_check": "required"}))
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    view = client.get(f"/api/admin/session/{session_id}/recording").json()
    assert (view["next_consent_kind"], view["id_check"]) == ("first", "required")
    with open_guest_socket(client, session_id, ORIGIN):
        refused = client.post(
            f"/api/admin/session/{session_id}/recording/request",
            json={"request_id": str(uuid.uuid4())},
        )
        assert _error(refused) == (422, "ID_CHECK_REQUIRED")
        _ask(client, session_id, id_checked=True)


def test_the_consent_text_is_read_aloud_in_the_guests_language(
    client, conversations, recording, gateway_dependencies, monkeypatch
) -> None:
    voice = _Voice()
    monkeypatch.setattr(gateway_dependencies.speech_pipeline, "speech", voice)
    session_id = conversations.create()
    conversations.activate(session_id, "uk")
    audio = f"/api/customer/session/{session_id}/recording/consent/audio"
    text = consent_text(POLICY, "uk", "first")
    with open_guest_socket(client, session_id, ORIGIN):
        request_id = _ask(client, session_id)
        url = f"{audio}?request_id={request_id}&text_sha256={text.sha256}"
        stale = client.get(f"{audio}?request_id={uuid.uuid4()}&text_sha256={text.sha256}")
        assert _error(stale) == (409, "RECORDING_REQUEST_STALE")
        changed = client.get(f"{audio}?request_id={request_id}&text_sha256={'0' * 64}")
        assert _error(changed) == (409, "CONSENT_TEXT_MISMATCH")

        voice.content_type = "application/json"
        assert _error(client.get(url)) == (503, "READ_ALOUD_UNAVAILABLE")
        voice.fails = True
        assert _error(client.get(url)) == (503, "READ_ALOUD_UNAVAILABLE")

        voice.fails, voice.content_type = False, "audio/wav"
        spoken = client.get(url)
        assert (spoken.status_code, spoken.headers["content-type"], spoken.content) == (
            200,
            "audio/wav",
            b"RIFF-read-aloud",
        )
        assert voice.payloads[-1] == {"text": text.plain(), "lang": "uk", "debug": "false"}
        voice.fails = True
        assert client.get(url).content == b"RIFF-read-aloud"  # read once, kept


MARKER = "Zebrastreifen-7f3c"


def _files_holding(root, needle: bytes) -> list[str]:
    return [str(path) for path in root.rglob("*") if path.is_file() and needle in path.read_bytes()]


def test_no_plaintext_outlives_its_conversation(
    client, conversations, recording, speech_services, gateway_dependencies, caplog, tmp_path
) -> None:
    """Spec §20 "no plaintext at rest", for what this process writes: a marker spoken
    and typed into a recorded conversation is, once it ends, in no file the archive,
    the spool or delivery left, in no log line, and not in the terminal record."""
    caplog.set_level(logging.DEBUG)  # every level the gateway logs at
    speech_services.asr_text = f"Ich heiße {MARKER}"
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    key = TenantSessionKey(TENANT_A, session_id)
    with _admin_socket(client, conversations, session_id) as admin:
        with open_guest_socket(client, session_id, ORIGIN) as guest:
            _turn_on(client, conversations, session_id, admin, guest)
            spoken = client.post(
                f"/api/admin/session/{session_id}/message",
                files={"file": ("speech.wav", wav_bytes(), "audio/wav")},
                data={"source_lang": "de", "target_lang": "en"},
            )
            typed = client.post(
                f"/api/customer/session/{session_id}/message",
                json={"text": f"Mein Name ist {MARKER}", "source_lang": "en", "target_lang": "de"},
            )
            assert (spoken.status_code, typed.status_code) == (200, 200)
            live = client.portal.call(gateway_dependencies.session_manager.store.load, key)
            assert MARKER in json.dumps(live.to_dict(include_messages=True))  # not vacuous
    assert _kinds(recording)[-2:] == ["message", "message"]
    assert client.portal.call(recording.rig.spools.flush)

    conversations.terminate(session_id)

    needle = MARKER.encode()
    # The recording rig keeps its spool and archive store under this test's tmp_path.
    assert _files_holding(tmp_path, needle) == []  # spool and archive store: ciphertext only
    audio = gateway_dependencies.audio_store.base_dir / "v2"
    assert not any(audio.rglob(f"*{session_id}*")), "delivery audio outlived the session"
    ended = client.portal.call(gateway_dependencies.session_manager.store.load, key)
    assert ended.messages == [] and MARKER not in json.dumps(ended.to_dict(include_messages=True))
    assert MARKER not in caplog.text


def test_a_recorded_conversation_withholds_its_languages_from_the_pipelines_telemetry(
    client, conversations, recording, speech_services, monkeypatch
) -> None:
    """Spec §5.5: from the first yes on, the refiner's events name no language."""
    from services.api_gateway import message_processing

    withheld: list[tuple[str, bool]] = []

    def spying(name: str) -> Any:
        real = getattr(message_processing, name)

        def spy(*args: Any, **kwargs: Any) -> Any:
            withheld.append((name, kwargs["withhold_languages"]))
            return real(*args, **kwargs)

        return spy

    for name in ("process_text_pipeline", "process_wav"):
        monkeypatch.setattr(message_processing, name, spying(name))
    session_id = conversations.create()
    conversations.activate(session_id, "en")

    def speak() -> int:
        return client.post(
            f"/api/admin/session/{session_id}/message",
            files={"file": ("speech.wav", wav_bytes(), "audio/wav")},
            data={"source_lang": "de", "target_lang": "en"},
        ).status_code

    with _admin_socket(client, conversations, session_id) as admin:
        with open_guest_socket(client, session_id, ORIGIN) as guest:
            assert (conversations.send_text(session_id).status_code, speak()) == (200, 200)
            _turn_on(client, conversations, session_id, admin, guest)
            assert (conversations.send_text(session_id).status_code, speak()) == (200, 200)

    assert withheld == [
        ("process_text_pipeline", False),
        ("process_wav", False),
        ("process_text_pipeline", True),
        ("process_wav", True),
    ]


def test_studio_bilateral_release_is_enforced_by_real_routes(
    client, conversations, recording, monkeypatch
):
    from tests.test_studio_recording_legal_texts import legal_block, runtime

    monkeypatch.setattr(__name__ + ".POLICY", runtime(legal_block()).policy.recording)
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    admin_base = f"/api/admin/session/{session_id}/recording"
    guest_base = f"/api/customer/session/{session_id}/recording"
    with _admin_socket(client, conversations, session_id):
        with open_guest_socket(client, session_id, ORIGIN):
            view = client.get(admin_base).json()
            release = view["staff_release"]
            assert release["language"] == "de"
            assert "Employee release body" in release["html"]
            request_id = str(uuid.uuid4())
            missing = client.post(admin_base + "/request", json={"request_id": request_id})
            assert missing.status_code == 409
            assert missing.json()["detail"]["error_code"] == "STAFF_RELEASE_TEXT_MISMATCH"
            requested = client.post(
                admin_base + "/request",
                json={"request_id": request_id, "staff_release_sha256": release["sha256"]},
            )
            assert requested.status_code == 200
            text = client.get(guest_base + "/consent").json()
            assert text["accept_label"] == "Accept Guest release"
            assert text["documentation_consent"]["accept_label"] == "Accept Documentation"
            answer = {
                "request_id": request_id,
                "consent": True,
                "text_sha256": text["text_sha256"],
                "name": "Guest",
            }
            refused = client.post(guest_base + "/answer", json=answer)
            assert refused.status_code == 422
            assert refused.json()["detail"]["error_code"] == "DOCUMENTATION_CONSENT_REQUIRED"
            accepted = client.post(
                guest_base + "/answer", json=answer | {"documentation_consent": True}
            )
            assert accepted.status_code == 200
            assert accepted.json()["state"] == "arming"
            assert client.post(admin_base + "/stop").status_code == 200
