"""How a test acts as the session's one guest."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi.testclient import TestClient

GUEST_TOKEN_HEADER = "X-Guest-Token"


def guest_headers(token: str | None) -> dict[str, str]:
    return {GUEST_TOKEN_HEADER: token} if token else {}


def activate_guest(
    client: TestClient,
    session_id: str,
    language: str = "en",
    *,
    consent: bool | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    """Activate as the guest; the body's `guest_token` is set on the first activation."""
    body: dict[str, Any] = {"session_id": session_id, "customer_language": language}
    if consent is not None:
        body["data_retention_consent"] = consent
    response = client.post(
        "/api/customer/session/activate", json=body, headers=guest_headers(token)
    )
    assert response.status_code == 200, response.text
    return response.json()


def guest_socket_path(client: TestClient, session_id: str, token: str | None) -> str:
    """A one-time guest socket path; the session must be active."""
    issued = client.post(
        f"/api/customer/session/{session_id}/realtime-ticket", headers=guest_headers(token)
    )
    assert issued.status_code == 200, issued.text
    return f"/ws/customer/{session_id}?ticket={quote(issued.json()['ticket'], safe='')}"


def join_as_guest(client: TestClient, session_id: str, language: str = "en") -> str:
    """Activate as the guest and send its token on every later request of `client`."""
    token = activate_guest(client, session_id, language)["guest_token"]
    client.headers[GUEST_TOKEN_HEADER] = token
    return token


def ensure_guest(client: TestClient, session_id: str, language: str = "en") -> str:
    """Claim the session unless this client already holds its token.

    For the contract suite's client, which remembers a token per session and
    sends it on that session's guest requests.
    """
    tokens: dict[str, str] = client.guest_tokens  # type: ignore[attr-defined]
    if session_id not in tokens:
        tokens[session_id] = activate_guest(client, session_id, language)["guest_token"]
    return tokens[session_id]


def open_guest_socket(client: TestClient, session_id: str, headers: dict[str, str]):
    """The session's guest socket on a fresh one-time ticket, claiming the session first."""
    ensure_guest(client, session_id)
    return client.websocket_connect(guest_socket_path(client, session_id, None), headers=headers)
