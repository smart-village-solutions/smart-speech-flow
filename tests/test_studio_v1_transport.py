"""The default Studio V1 transport against a real HTTP server."""

import pytest
from aiohttp import web

from services.api_gateway.studio_v1 import AiohttpStudioV1Transport, StudioV1HttpResponse


async def _serve(handler) -> tuple[web.AppRunner, str]:
    app = web.Application()
    app.router.add_get("/", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0).start()
    port = runner.addresses[0][1]
    return runner, f"http://127.0.0.1:{port}/"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (web.json_response({"ok": True}), StudioV1HttpResponse(200, {"ok": True})),
        (web.json_response(["not", "an", "object"], status=200), StudioV1HttpResponse(200, None)),
        (web.Response(text="<html>Bad Gateway</html>", status=502), StudioV1HttpResponse(502, None)),
    ],
    ids=["json-object", "json-array", "html-error-page"],
)
async def test_returns_status_and_only_a_json_object_payload(
    response: web.Response, expected: StudioV1HttpResponse
) -> None:
    seen_headers: dict[str, str] = {}

    async def handler(request: web.Request) -> web.Response:
        seen_headers.update(request.headers)
        return response

    runner, url = await _serve(handler)
    try:
        result = await AiohttpStudioV1Transport().get(url, {"X-Correlation-Id": "c1"}, 2.0)
    finally:
        await runner.cleanup()

    assert result == expected
    assert seen_headers["X-Correlation-Id"] == "c1"
