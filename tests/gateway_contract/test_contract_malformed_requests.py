"""A malformed message body is the client's error: 400, never 500 (#230).

Both cases used to reach send_unified_message's catch-all and answer 500.
"""

from __future__ import annotations

import pytest

ERROR_FIELDS = {"status", "error_code", "error_message", "details", "timestamp"}


@pytest.fixture
def active_session(conversations) -> str:
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    return session_id


def _error(response) -> dict:
    detail = response.json()["detail"]
    assert set(detail) == ERROR_FIELDS
    return detail


@pytest.mark.usefixtures("speech_services")
@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        # Starlette answers these itself with its own HTTPException(400) ...
        (b"--x\r\n", "multipart/form-data"),
        # ... and lets python-multipart's parse errors escape raw.
        (
            b"--x\r\nContent-Disposition form-data\r\n\r\nv\r\n--x--\r\n",
            "multipart/form-data; boundary=x",
        ),
        (b"\xff\xfe\x00garbage", "multipart/form-data; boundary=x"),
    ],
    ids=["no-boundary", "bad-part-header", "garbage"],
)
def test_a_malformed_multipart_body_is_a_400(client, active_session, body, content_type):
    response = client.post(
        f"/api/admin/session/{active_session}/message",
        content=body,
        headers={"content-type": content_type},
    )

    assert response.status_code == 400
    assert _error(response)["error_code"] == "INVALID_FORM_DATA"


@pytest.mark.usefixtures("speech_services")
@pytest.mark.parametrize("body", [b"[]", b'"hello"', b"null", b"42"], ids=str)
def test_json_that_is_not_an_object_is_a_400(client, active_session, body):
    response = client.post(
        f"/api/admin/session/{active_session}/message",
        content=body,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400
    assert _error(response)["error_code"] == "INVALID_JSON"
