"""A session admits one guest: the browser that activated it first."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from services.api_gateway.app import app

HEADER = "X-Guest-Token"


@pytest.fixture
def client(session_manager, request: pytest.FixtureRequest) -> TestClient:
    session_manager.reset(clear_persistence=True)
    return TestClient(app, client=(request.node.nodeid, 50000))


def _create(client: TestClient) -> str:
    created = client.post("/api/admin/session/create")
    assert created.status_code == 201, created.text
    return created.json()["session_id"]


def _activate(client: TestClient, session_id: str, language: str, token: str | None = None):
    headers = {HEADER: token} if token else {}
    return client.post(
        "/api/customer/session/activate",
        json={"session_id": session_id, "customer_language": language},
        headers=headers,
    )


def _claimed(client: TestClient) -> tuple[str, str]:
    session_id = _create(client)
    activated = _activate(client, session_id, "en")
    assert activated.status_code == 200, activated.text
    token = activated.json()["guest_token"]
    assert token
    return session_id, token


def _refused(response) -> None:
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["error_code"] == "SESSION_HAS_GUEST"


def test_a_second_browser_cannot_activate_a_claimed_session(client) -> None:
    session_id, _ = _claimed(client)

    _refused(_activate(client, session_id, "tr"))
    _refused(_activate(client, session_id, "en"))
    _refused(_activate(client, session_id, "tr", "wrong"))
    status = client.get(f"/api/admin/session/{session_id}/status")
    assert status.json()["customer_language"] == "en"


def test_the_holder_switches_language_without_a_new_token(client) -> None:
    session_id, token = _claimed(client)

    switched = _activate(client, session_id, "tr", token)

    assert switched.status_code == 200, switched.text
    assert switched.json()["customer_language"] == "tr"
    assert switched.json()["guest_token"] is None


@pytest.mark.parametrize(
    "method, path",
    [
        ("get", "/api/customer/session/{id}"),
        ("get", "/api/customer/session/{id}/messages"),
        ("post", "/api/customer/session/{id}/message"),
        ("get", "/api/customer/session/{id}/audio/m1/translated.wav"),
    ],
)
def test_every_guest_route_refuses_a_stranger_and_admits_the_holder(client, method, path) -> None:
    session_id, token = _claimed(client)
    url = path.format(id=session_id)
    body = (
        {"json": {"text": "Hallo", "source_lang": "en", "target_lang": "de"}}
        if method == "post"
        else {}
    )

    _refused(getattr(client, method)(url, **body))
    _refused(getattr(client, method)(url, headers={HEADER: "wrong"}, **body))
    assert getattr(client, method)(url, headers={HEADER: token}, **body).status_code != 409


def test_display_content_stays_open(client) -> None:
    session_id, _ = _claimed(client)

    assert client.get(f"/api/customer/session/{session_id}/languages").status_code == 200


def test_a_pending_session_needs_no_token(client) -> None:
    session_id = _create(client)

    assert client.get(f"/api/customer/session/{session_id}").status_code == 200


ORIGIN = {"Origin": "https://translate.smart-village.solutions"}


@pytest.fixture
def sockets(session_manager, gateway_dependencies):
    session_manager.register_websocket_manager(gateway_dependencies.websocket_manager)


def _ticket(client: TestClient, session_id: str, token: str | None = None):
    headers = {HEADER: token} if token else {}
    return client.post(f"/api/customer/session/{session_id}/realtime-ticket", headers=headers)


def test_the_holder_gets_a_ticket_and_the_socket_opens_with_it(client, sockets) -> None:
    session_id, token = _claimed(client)
    issued = _ticket(client, session_id, token)
    assert issued.status_code == 200, issued.text

    with client.websocket_connect(
        f"/ws/customer/{session_id}?ticket={issued.json()['ticket']}", headers=ORIGIN
    ) as socket:
        assert socket.receive_json()["type"] == "connection_ack"


def test_a_ticket_opens_the_socket_once(client, sockets) -> None:
    session_id, token = _claimed(client)
    ticket = _ticket(client, session_id, token).json()["ticket"]
    path = f"/ws/customer/{session_id}?ticket={ticket}"
    with client.websocket_connect(path, headers=ORIGIN) as socket:
        socket.receive_json()

    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(path, headers=ORIGIN):
            pass

    assert closed.value.code == 4403


def test_a_stranger_gets_no_ticket(client) -> None:
    session_id, _ = _claimed(client)

    _refused(_ticket(client, session_id))


@pytest.mark.parametrize("route", ["realtime-ticket", "polling/activate"])
def test_a_pending_session_offers_no_realtime_connection(client, route) -> None:
    session_id = _create(client)

    response = client.post(f"/api/customer/session/{session_id}/{route}")

    assert response.status_code == 400, response.text
    assert response.json()["detail"]["error_code"] == "SESSION_NOT_ACTIVE"


@pytest.mark.parametrize("claimed", [True, False], ids=["claimed", "pending"])
def test_the_socket_refuses_a_missing_ticket_on_a_claimed_or_pending_session(
    client, sockets, claimed
) -> None:
    session_id = _create(client)
    if claimed:
        assert _activate(client, session_id, "en").status_code == 200

    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(f"/ws/customer/{session_id}", headers=ORIGIN):
            pass

    assert closed.value.code == 4403


async def test_a_session_activated_before_tokens_still_takes_a_ticketless_socket(
    client, session_manager, sockets
) -> None:
    session_id, _ = _claimed(client)
    key = await session_manager.resolve_customer_session(session_id)
    session = await session_manager.get_session(key)
    session.guest_token_hash = None

    with client.websocket_connect(f"/ws/customer/{session_id}", headers=ORIGIN) as socket:
        assert socket.receive_json()["type"] == "connection_ack"


def test_the_holder_polls_and_a_stranger_does_not(client) -> None:
    session_id, token = _claimed(client)
    url = f"/api/customer/session/{session_id}/polling/activate"

    _refused(client.post(url))
    assert client.post(url, headers={HEADER: token}).status_code == 200


@pytest.mark.parametrize(
    "role, body, code",
    [
        ("customer", {"source_lang": "tr", "target_lang": "de"}, "INVALID_SOURCE_LANGUAGE"),
        ("admin", {"source_lang": "de", "target_lang": "tr"}, "INVALID_TARGET_LANGUAGE"),
    ],
)
def test_a_language_mismatch_carries_error_code_beside_error_type(client, role, body, code) -> None:
    session_id, token = _claimed(client)

    response = client.post(
        f"/api/{role}/session/{session_id}/message",
        json={"text": "Hallo", **body},
        headers={HEADER: token},
    )

    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert detail["error_code"] == code and detail["error_type"] == code
