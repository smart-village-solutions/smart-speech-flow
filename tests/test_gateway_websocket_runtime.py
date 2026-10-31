"""Exercise the gateway image's WebSocket launch options over a real socket."""

import asyncio
import json
import secrets
import socket
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosedError


@asynccontextmanager
async def gateway_runtime(tmp_path):
    dockerfile = Path(__file__).resolve().parents[1] / "services/api_gateway/Dockerfile"
    command = json.loads(
        next(
            line.removeprefix("CMD ")
            for line in dockerfile.read_text().splitlines()
            if line.startswith("CMD ")
        )
    )
    # Substitute only the application. The production protocol options must
    # reject excessive fragments before any ASGI application receives them.
    command[command.index("services.api_gateway.app:app")] = "probe:app"
    (tmp_path / "probe.py").write_text(
        "from fastapi import FastAPI, WebSocket\n"
        "app = FastAPI()\n"
        "@app.websocket('/echo')\n"
        "async def echo(ws: WebSocket):\n"
        "    await ws.accept()\n"
        "    while True:\n"
        "        message = await ws.receive()\n"
        "        if message['type'] == 'websocket.disconnect':\n"
        "            return\n"
        "        await ws.send_text(message['text'])\n"
    )
    with socket.socket() as listener, (tmp_path / "server.log").open("w+") as log:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                *command,
                "--app-dir",
                str(tmp_path),
                "--fd",
                str(listener.fileno()),
            ],
            pass_fds=(listener.fileno(),),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(100):
                if process.poll() is not None:
                    log.seek(0)
                    pytest.fail(log.read())
                try:
                    client = await connect(
                        f"ws://127.0.0.1:{port}/echo", open_timeout=0.1, proxy=None
                    )
                    break
                except (OSError, TimeoutError):
                    await asyncio.sleep(0.05)
            else:
                pytest.fail("Gateway WebSocket runtime never accepted a connection")
            await client.close()
            yield f"ws://127.0.0.1:{port}/echo"
        finally:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait, timeout=10)


@pytest.mark.asyncio
async def test_gateway_runtime_rejects_excessive_fragments(tmp_path):
    async with gateway_runtime(tmp_path) as url, connect(url, proxy=None) as client:
        await client.send(["fragmented ", "Grüße"])
        assert await asyncio.wait_for(client.recv(), 2) == "fragmented Grüße"
        await client.send(["x"] * 4097)
        with pytest.raises(ConnectionClosedError) as closed:
            await asyncio.wait_for(client.recv(), 2)
        assert closed.value.rcvd is not None
        assert closed.value.rcvd.code == 1009


@pytest.mark.asyncio
async def test_gateway_runtime_does_not_log_websocket_tickets(tmp_path):
    ticket = secrets.token_urlsafe(18)
    async with gateway_runtime(tmp_path) as url:
        async with connect(f"{url}?ticket={ticket}", proxy=None) as client:
            await client.send("ordinary message")
            assert await asyncio.wait_for(client.recv(), 2) == "ordinary message"
    assert ticket not in (tmp_path / "server.log").read_text()
