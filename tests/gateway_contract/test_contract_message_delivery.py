"""A message sent over HTTP reaches both parties' live WebSockets.

The receiver gets the translation with audio URLs scoped to its own role; the
sender gets a confirmation carrying its original text. This is the product's
main flow, and nothing else in this suite drives it end to end.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.gateway_contract.contract_support import ALLOWED_ORIGIN, wav_bytes

ORIGIN = {"Origin": ALLOWED_ORIGIN}
LANGUAGES = {"admin": ("de", "en"), "customer": ("en", "de")}
PEER = {"admin": "customer", "customer": "admin"}
MESSAGE_FIELDS = {
    "status",
    "message_id",
    "session_id",
    "original_text",
    "translated_text",
    "audio_available",
    "audio_url",
    "processing_time_ms",
    "pipeline_type",
    "source_lang",
    "target_lang",
    "timestamp",
    "pipeline_metadata",
}

pytestmark = pytest.mark.usefixtures("speech_services")


def _audio_url(role: str, session_id: str, message_id: str, variant: str) -> str:
    return f"/api/{role}/session/{session_id}/audio/{message_id}/{variant}.wav"


def _rescoped(metadata: dict[str, Any], sender: str, receiver: str) -> dict[str, Any]:
    """The sender-scoped pipeline metadata as the receiver's role sees it."""
    text = json.dumps(metadata).replace(f"/api/{sender}/session/", f"/api/{receiver}/session/")
    rescoped: dict[str, Any] = json.loads(text)
    return rescoped


def _post(client, session_id: str, sender: str, mode: str):
    source, target = LANGUAGES[sender]
    url = f"/api/{sender}/session/{session_id}/message"
    if mode == "audio":
        return client.post(
            url,
            files={"file": ("speech.wav", wav_bytes(), "audio/wav")},
            data={"source_lang": source, "target_lang": target},
        )
    return client.post(
        url, json={"text": "Guten Tag", "source_lang": source, "target_lang": target}
    )


def _next_frame_before_a_sentinel(socket) -> dict[str, Any]:
    """The frame already queued on `socket`, or the sentinel's error if there is none.

    A malformed frame is always answered with an error, after anything the
    server sent earlier. Reading up to that answer turns a missing delivery
    into a failed assertion instead of a receive that blocks forever.
    """
    socket.send_text("not json")
    frame: dict[str, Any] = socket.receive_json()
    if frame.get("type") != "error":
        assert socket.receive_json()["type"] == "error"
    return frame


@pytest.mark.parametrize("mode", ["text", "audio"])
@pytest.mark.parametrize("sender", ["admin", "customer"])
def test_an_http_message_reaches_both_live_websockets(client, conversations, sender, mode):
    receiver = PEER[sender]
    source, target = LANGUAGES[sender]
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    ticket = conversations.ticket(session_id)

    with client.websocket_connect(
        f"/ws/admin/{session_id}?ticket={ticket}", headers=ORIGIN
    ) as admin_socket:
        assert admin_socket.receive_json()["type"] == "connection_ack"
        with client.websocket_connect(
            f"/ws/customer/{session_id}", headers=ORIGIN
        ) as customer_socket:
            assert customer_socket.receive_json()["type"] == "connection_ack"
            assert admin_socket.receive_json()["type"] == "client_joined"

            response = _post(client, session_id, sender, mode)
            frames = {
                role: _next_frame_before_a_sentinel(socket)
                for role, socket in (("admin", admin_socket), ("customer", customer_socket))
            }

    assert response.status_code == 200, response.text
    body = response.json()
    message_id = body["message_id"]
    assert set(body) == MESSAGE_FIELDS
    assert {
        key: body[key]
        for key in (
            "status",
            "session_id",
            "original_text",
            "translated_text",
            "audio_available",
            "audio_url",
            "pipeline_type",
            "source_lang",
            "target_lang",
        )
    } == {
        "status": "success",
        "session_id": session_id,
        "original_text": "Guten Tag",
        "translated_text": "Good day",
        "audio_available": True,
        "audio_url": _audio_url(sender, session_id, message_id, "translated"),
        "pipeline_type": mode,
        "source_lang": source,
        "target_lang": target,
    }

    common = {
        "type": "message",
        "message_id": message_id,
        "session_id": session_id,
        "source_lang": source,
        "target_lang": target,
        "sender": sender,
        "timestamp": body["timestamp"],
    }
    expected_receiver: dict[str, Any] = {
        **common,
        "text": "Good day",
        "audio_available": True,
        "audio_url": _audio_url(receiver, session_id, message_id, "translated"),
        "role": "receiver_message",
        "pipeline_metadata": _rescoped(body["pipeline_metadata"], sender, receiver),
    }
    # The sender hears nothing back; its confirmation has no translated audio at all.
    expected_sender: dict[str, Any] = {
        **common,
        "text": "Guten Tag",
        "audio_available": False,
        "role": "sender_confirmation",
        "pipeline_metadata": body["pipeline_metadata"],
    }
    if mode == "audio":
        expected_receiver["original_audio_url"] = _audio_url(
            receiver, session_id, message_id, "original"
        )
        expected_sender["original_audio_url"] = _audio_url(
            sender, session_id, message_id, "original"
        )

    assert frames[receiver] == expected_receiver
    assert frames[sender] == expected_sender
