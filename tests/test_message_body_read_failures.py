"""A client that drops while sending its body gets a 400, not a server error (#230).

Starlette raises ClientDisconnect (a plain Exception) from body(), json() and form().
The narrowed parsers must still answer it as the client's error, as main did.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from starlette.requests import ClientDisconnect

from services.api_gateway import message_requests


def _request_failing_with(error: Exception) -> Mock:
    request = Mock()
    request.json = AsyncMock(side_effect=error)
    request.form = AsyncMock(side_effect=error)
    return request


@pytest.mark.asyncio
async def test_a_disconnect_while_sending_json_is_a_400():
    request = _request_failing_with(ClientDisconnect())

    with pytest.raises(HTTPException) as raised:
        await message_requests._parse_text_request(request)

    assert raised.value.status_code == 400
    assert raised.value.detail["error_code"] == "INVALID_JSON"


@pytest.mark.asyncio
async def test_a_disconnect_while_sending_a_form_is_a_400():
    request = _request_failing_with(ClientDisconnect())

    with pytest.raises(HTTPException) as raised:
        await message_requests._parse_audio_form(request)

    assert raised.value.status_code == 400
    assert raised.value.detail["error_code"] == "INVALID_FORM_DATA"
