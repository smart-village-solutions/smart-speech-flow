"""Every frame the realtime surface sends, by key set and fixed values.

Clients parse these frames by key, so a key that appears, disappears or changes
its value breaks them without failing anything else. Each test drives real
sockets, and pollers where the frame also reaches them. Timestamps and ids are
checked for presence and type only.

The heartbeat's `connection_status` frame and its close are pinned in
test_contract_heartbeat.py, and the polled `send` envelope in
test_contract_polling.py.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import pytest

from tests.gateway_contract.contract_support import ALLOWED_ORIGIN

ORIGIN = {"Origin": ALLOWED_ORIGIN}
RELAY_KEYS = {"type", "from", "session_id", "content", "timestamp"}
TYPING_KEYS = {"type", "from", "session_id", "is_typing", "timestamp"}
JOINED_KEYS = {"type", "session_id", "client_type", "connection_id", "timestamp"}
LEFT_KEYS = {"type", "session_id", "client_type", "connection_id", "reason", "timestamp"}
INTERVAL_KEYS = {
    "type",
    "new_interval",
    "old_interval",
    "reason",
    "optimization_tips",
    "battery_level",
    "is_mobile",
    "tab_active",
    "timestamp",
}
BATTERY_SAVER = {
    "type": "battery_saver_mode",
    "title": "🔋 Battery-Saver aktiviert",
    "message": "Update-Frequenz wurde auf 60 Sekunden reduziert um Akku zu schonen.",
    "new_polling_interval": 60,
    "tips": [
        "📱 Tab schließen wenn nicht benötigt",
        "🔌 Gerät ans Ladegerät anschließen",
        "⚡ Battery-Saver-Modus deaktivieren für normale Geschwindigkeit",
    ],
}
SENDER_KEYS = {
    "type",
    "message_id",
    "session_id",
    "text",
    "source_lang",
    "target_lang",
    "sender",
    "timestamp",
    "audio_available",
    "role",
    "pipeline_metadata",
}


def _admin_socket(client, conversations, session_id: str):
    ticket = conversations.ticket(session_id)
    return client.websocket_connect(f"/ws/admin/{session_id}?ticket={ticket}", headers=ORIGIN)


def _customer_socket(client, session_id: str):
    return client.websocket_connect(f"/ws/customer/{session_id}", headers=ORIGIN)


def _customer_poller(client, session_id: str) -> str:
    response = client.post(f"/api/customer/session/{session_id}/polling/activate")
    assert response.status_code == 200, response.text
    polling_id: str = response.json()["polling_id"]
    return polling_id


def _admin_poller(client, conversations, session_id: str) -> str:
    ticket = conversations.ticket(session_id, "polling")
    response = client.post(
        f"/api/admin/session/{session_id}/polling/activate", json={"ticket": ticket}
    )
    assert response.status_code == 200, response.text
    polling_id: str = response.json()["polling_id"]
    return polling_id


def _polled(client, role: str, session_id: str, polling_id: str) -> list[dict[str, Any]]:
    response = client.get(f"/api/{role}/session/{session_id}/polling/{polling_id}")
    assert response.status_code == 200, response.text
    messages: list[dict[str, Any]] = response.json()["messages"]
    return messages


def _before_a_sentinel(socket) -> list[dict[str, Any]]:
    """Every frame already queued on `socket`, read up to the answer to a malformed frame."""
    socket.send_text("not json")
    frames: list[dict[str, Any]] = []
    while True:
        frame: dict[str, Any] = socket.receive_json()
        if frame["type"] == "error":
            return frames
        frames.append(frame)


def _is_timestamp(value: object) -> bool:
    return isinstance(value, str) and datetime.fromisoformat(value).tzinfo is not None


def _without(frame: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: value for key, value in frame.items() if key not in keys}


@pytest.fixture
def fast_heartbeat(gateway_dependencies):
    manager = gateway_dependencies.websocket_manager
    manager.heartbeat_interval = 0.05
    return manager


@pytest.mark.parametrize("role", ["admin", "customer"])
def test_connection_ack(client, conversations, role):
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    opened = (
        _admin_socket(client, conversations, session_id)
        if role == "admin"
        else _customer_socket(client, session_id)
    )

    with opened as socket:
        ack = socket.receive_json()

    assert _without(ack, "timestamp") == {
        "type": "connection_ack",
        "session_id": session_id,
        "client_type": role,
        "heartbeat_interval": 30,
    }
    assert _is_timestamp(ack["timestamp"])


def test_heartbeat_ping(client, conversations, fast_heartbeat):
    session_id = conversations.create()

    with _admin_socket(client, conversations, session_id) as socket:
        socket.receive_json()
        ping = socket.receive_json()

    assert set(ping) == {"type", "ping_id", "timestamp"}
    assert ping["type"] == "heartbeat_ping"
    assert re.fullmatch(r"[0-9a-f]{32}", ping["ping_id"])
    assert _is_timestamp(ping["timestamp"])


@pytest.mark.parametrize(
    "sent",
    [lambda socket: socket.send_text("not json"), lambda socket: socket.send_json([1, 2])],
    ids=["malformed", "not-an-object"],
)
def test_error(client, conversations, sent):
    session_id = conversations.create()

    with _admin_socket(client, conversations, session_id) as socket:
        socket.receive_json()
        sent(socket)
        error = socket.receive_json()

    assert _without(error, "timestamp") == {"type": "error", "error": "Message processing failed"}
    assert _is_timestamp(error["timestamp"])


def test_client_joined_and_left_reach_the_peer_and_the_pollers(client, conversations):
    session_id = conversations.create()
    conversations.activate(session_id, "ar")
    poller = _customer_poller(client, session_id)

    with _admin_socket(client, conversations, session_id) as admin:
        admin.receive_json()
        with _customer_socket(client, session_id) as customer:
            customer.receive_json()
            joined = admin.receive_json()
            customer.close()
            left = admin.receive_json()
        polled = _polled(client, "customer", session_id, poller)

    assert set(joined) == JOINED_KEYS | {"customer_language"}
    assert _without(joined, "timestamp", "connection_id") == {
        "type": "client_joined",
        "session_id": session_id,
        "client_type": "customer",
        "customer_language": "ar",
    }
    assert set(left) == LEFT_KEYS
    assert _without(left, "timestamp", "connection_id") == {
        "type": "client_left",
        "session_id": session_id,
        "client_type": "customer",
        "reason": "client_disconnect",
    }
    assert left["connection_id"] == joined["connection_id"]
    assert isinstance(joined["connection_id"], str)
    assert _is_timestamp(joined["timestamp"])
    assert _is_timestamp(left["timestamp"])
    # The admin's own join reaches the poller as well.
    assert [(frame["type"], frame["client_type"]) for frame in polled] == [
        ("client_joined", "admin"),
        ("client_joined", "customer"),
        ("client_left", "customer"),
    ]
    assert set(polled[0]) == JOINED_KEYS
    assert polled[1:] == [joined, left]


def test_an_admin_join_carries_no_customer_language(client, conversations):
    session_id = conversations.create()
    conversations.activate(session_id, "ar")

    with _customer_socket(client, session_id) as customer:
        customer.receive_json()
        with _admin_socket(client, conversations, session_id) as admin:
            admin.receive_json()
            joined = customer.receive_json()

    assert set(joined) == JOINED_KEYS
    assert (joined["type"], joined["client_type"]) == ("client_joined", "admin")


def test_a_customer_join_before_activation_carries_no_customer_language(client, conversations):
    session_id = conversations.create()

    with _admin_socket(client, conversations, session_id) as admin:
        admin.receive_json()
        with _customer_socket(client, session_id) as customer:
            customer.receive_json()
            joined = admin.receive_json()

    assert set(joined) == JOINED_KEYS
    assert (joined["type"], joined["client_type"]) == ("client_joined", "customer")


@pytest.mark.parametrize(
    ("sent", "content"),
    [
        ({"type": "message", "content": {"text": "hallo"}}, {"text": "hallo"}),
        ({"type": "message", "content": "plain"}, "plain"),
        ({"type": "message"}, None),
    ],
    ids=["object", "string", "missing"],
)
def test_a_relayed_message_reaches_the_peer_and_the_pollers_but_not_the_sender(
    client, conversations, sent, content
):
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    poller = _customer_poller(client, session_id)

    with _admin_socket(client, conversations, session_id) as admin:
        admin.receive_json()
        with _customer_socket(client, session_id) as customer:
            customer.receive_json()
            admin.receive_json()
            admin.send_json(sent)
            relayed = customer.receive_json()
            echoed = _before_a_sentinel(admin)
            _polled(client, "customer", session_id, poller)
            customer.send_json(sent)
            admin_received = admin.receive_json()
            polled_relay = _polled(client, "customer", session_id, poller)

    assert set(relayed) == RELAY_KEYS
    assert _without(relayed, "timestamp") == {
        "type": "message",
        "from": "admin",
        "session_id": session_id,
        "content": content,
    }
    assert _is_timestamp(relayed["timestamp"])
    assert echoed == []
    # A poller receives the relay whichever socket sent it, its own role's included.
    assert polled_relay == [admin_received]
    assert admin_received["from"] == "customer"


@pytest.mark.parametrize(
    ("sent", "is_typing"),
    [
        ({"type": "typing_indicator", "is_typing": True}, True),
        ({"type": "typing_indicator", "is_typing": False}, False),
        ({"type": "typing_indicator"}, False),
    ],
    ids=["typing", "stopped", "missing"],
)
def test_typing_reaches_the_peer_and_the_pollers(client, conversations, sent, is_typing):
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    poller = _admin_poller(client, conversations, session_id)

    with _admin_socket(client, conversations, session_id) as admin:
        admin.receive_json()
        with _customer_socket(client, session_id) as customer:
            customer.receive_json()
            admin.receive_json()
            _polled(client, "admin", session_id, poller)
            customer.send_json(sent)
            typing = admin.receive_json()
            echoed = _before_a_sentinel(customer)
            polled = _polled(client, "admin", session_id, poller)

    assert set(typing) == TYPING_KEYS
    assert _without(typing, "timestamp") == {
        "type": "typing_indicator",
        "from": "customer",
        "session_id": session_id,
        "is_typing": is_typing,
    }
    assert _is_timestamp(typing["timestamp"])
    assert echoed == []
    assert polled == [typing]


@pytest.mark.usefixtures("speech_services")
@pytest.mark.parametrize("sender", ["admin", "customer"])
def test_a_differentiated_message_reaches_each_role_on_both_transports(
    client, conversations, sender
):
    receiver = "customer" if sender == "admin" else "admin"
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    pollers = {
        "admin": _admin_poller(client, conversations, session_id),
        "customer": _customer_poller(client, session_id),
    }
    languages = ("de", "en") if sender == "admin" else ("en", "de")

    with _admin_socket(client, conversations, session_id) as admin:
        admin.receive_json()
        with _customer_socket(client, session_id) as customer:
            customer.receive_json()
            admin.receive_json()
            for role, polling_id in pollers.items():
                _polled(client, role, session_id, polling_id)
            response = client.post(
                f"/api/{sender}/session/{session_id}/message",
                json={
                    "text": "Guten Tag",
                    "source_lang": languages[0],
                    "target_lang": languages[1],
                },
            )
            on_socket = {"admin": admin.receive_json(), "customer": customer.receive_json()}
            polled = {
                role: _polled(client, role, session_id, polling_id)
                for role, polling_id in pollers.items()
            }

    assert response.status_code == 200, response.text
    assert set(on_socket[sender]) == SENDER_KEYS
    assert set(on_socket[receiver]) == SENDER_KEYS | {"audio_url"}
    assert on_socket[sender]["role"] == "sender_confirmation"
    assert on_socket[receiver]["role"] == "receiver_message"
    assert (on_socket[sender]["type"], on_socket[receiver]["type"]) == ("message", "message")
    assert on_socket[sender]["audio_available"] is False
    for role in ("admin", "customer"):
        assert polled[role] == [on_socket[role]]


@pytest.mark.parametrize(
    ("reason", "text"),
    [
        ("manual_admin_termination", "Die Session wurde beendet."),
        ("new_session_created", "Die Session wurde beendet, da eine neue Session gestartet wurde."),
    ],
)
def test_session_terminated_on_both_transports(client, conversations, reason, text):
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    poller = _customer_poller(client, session_id)

    with _admin_socket(client, conversations, session_id) as admin:
        admin.receive_json()
        if reason == "new_session_created":
            conversations.create()
        else:
            conversations.terminate(session_id)
        terminated = admin.receive_json()
        polled = _polled(client, "customer", session_id, poller)

    assert _without(terminated, "timestamp") == {
        "type": "session_terminated",
        "session_id": session_id,
        "reason": reason,
        "message": text,
        "reconnect_allowed": False,
    }
    assert _is_timestamp(terminated["timestamp"])
    assert polled[-1] == {
        "type": "session_terminated",
        "session_id": session_id,
        "reason": reason,
        "reconnect_allowed": False,
    }


def test_timeout_warning_reaches_sockets_and_pollers(client, conversations, session_clock):
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    poller = _customer_poller(client, session_id)

    with _customer_socket(client, session_id) as customer:
        customer.receive_json()
        _polled(client, "customer", session_id, poller)
        # Without an admin, the warning is due five minutes before the 30-minute grace ends.
        session_clock.advance(minutes=26)
        session_clock.check_timeouts(client)
        warning = customer.receive_json()
        polled = _polled(client, "customer", session_id, poller)

    assert _without(warning, "timestamp") == {
        "type": "timeout_warning",
        "session_id": session_id,
        "message": "Session wird in 5 Minuten aufgrund von Inaktivität beendet.",
        "remaining_minutes": 5,
    }
    assert _is_timestamp(warning["timestamp"])
    assert polled == [warning]


def _interval_update(frame: dict[str, Any]) -> dict[str, Any]:
    assert set(frame) == INTERVAL_KEYS
    assert frame["type"] == "polling_interval_update"
    assert _is_timestamp(frame["timestamp"])
    return _without(frame, "type", "timestamp")


def test_tab_visibility_replies_only_to_the_sender(client, conversations):
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    poller = _customer_poller(client, session_id)

    with _admin_socket(client, conversations, session_id) as admin:
        admin.receive_json()
        with _customer_socket(client, session_id) as customer:
            customer.receive_json()
            admin.receive_json()
            _polled(client, "customer", session_id, poller)
            customer.send_json({"type": "tab_visibility_change", "is_visible": False})
            hidden = customer.receive_json()
            customer.send_json({"type": "tab_visibility_change", "is_visible": False})
            unchanged = _before_a_sentinel(customer)
            customer.send_json({"type": "tab_visibility_change", "is_visible": True})
            visible = customer.receive_json()
            peer = _before_a_sentinel(admin)
            polled = _polled(client, "customer", session_id, poller)

    # old_interval is read after the update, so it always equals new_interval.
    common = {"optimization_tips": [], "battery_level": 1.0, "is_mobile": False}
    assert _interval_update(hidden) == {
        **common,
        "new_interval": 10,
        "old_interval": 10,
        "reason": "background_optimization",
        "tab_active": False,
    }
    assert unchanged == []
    assert _interval_update(visible) == {
        **common,
        "new_interval": 3,
        "old_interval": 3,
        "reason": "tab_visibility_change",
        "tab_active": True,
    }
    assert peer == []
    assert polled == []


def test_a_low_battery_gets_the_battery_saver_frame_then_the_new_interval(client, conversations):
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    poller = _customer_poller(client, session_id)

    with _admin_socket(client, conversations, session_id) as admin:
        admin.receive_json()
        with _customer_socket(client, session_id) as customer:
            customer.receive_json()
            admin.receive_json()
            _polled(client, "customer", session_id, poller)
            customer.send_json(
                {"type": "battery_status_update", "battery_level": 0.1, "is_charging": False}
            )
            saver = customer.receive_json()
            update = customer.receive_json()
            customer.send_json(
                {"type": "battery_status_update", "battery_level": 0.1, "is_charging": False}
            )
            repeated = _before_a_sentinel(customer)
            peer = _before_a_sentinel(admin)
            polled = _polled(client, "customer", session_id, poller)

    assert _without(saver, "timestamp") == {**BATTERY_SAVER, "battery_level": 0.1}
    assert _is_timestamp(saver["timestamp"])
    assert _interval_update(update) == {
        "new_interval": 60,
        "old_interval": 60,
        "reason": "battery_optimization",
        "optimization_tips": ["🔋 Niedriger Akkustand - Polling-Intervall auf 60s erhöht"],
        "battery_level": 0.1,
        "is_mobile": False,
        "tab_active": True,
    }
    # The saver frame repeats with every low report; the interval did not change.
    assert [_without(frame, "timestamp") for frame in repeated] == [
        {**BATTERY_SAVER, "battery_level": 0.1}
    ]
    assert peer == []
    assert polled == []


def test_a_charging_low_battery_gets_only_the_new_interval(client, conversations):
    session_id = conversations.create()

    with _admin_socket(client, conversations, session_id) as admin:
        admin.receive_json()
        admin.send_json(
            {"type": "battery_status_update", "battery_level": 0.1, "is_charging": True}
        )
        frames = _before_a_sentinel(admin)

    assert [_interval_update(frame)["reason"] for frame in frames] == ["battery_optimization"]


@pytest.mark.parametrize(
    ("quality", "interval", "tips"),
    [
        ("slow", 15, ["📶 Langsame Verbindung erkannt - Polling angepasst"]),
        ("offline", 120, []),
    ],
)
def test_network_status_replies_only_to_the_sender(client, conversations, quality, interval, tips):
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    poller = _customer_poller(client, session_id)

    with _admin_socket(client, conversations, session_id) as admin:
        admin.receive_json()
        with _customer_socket(client, session_id) as customer:
            customer.receive_json()
            admin.receive_json()
            _polled(client, "customer", session_id, poller)
            customer.send_json({"type": "network_status_change", "network_quality": quality})
            update = customer.receive_json()
            customer.send_json({"type": "network_status_change", "network_quality": quality})
            unchanged = _before_a_sentinel(customer)
            peer = _before_a_sentinel(admin)
            polled = _polled(client, "customer", session_id, poller)

    assert _interval_update(update) == {
        "new_interval": interval,
        "old_interval": interval,
        "reason": f"network_{quality}",
        "optimization_tips": tips,
        "battery_level": 1.0,
        "is_mobile": False,
        "tab_active": True,
    }
    assert unchanged == []
    assert peer == []
    assert polled == []
