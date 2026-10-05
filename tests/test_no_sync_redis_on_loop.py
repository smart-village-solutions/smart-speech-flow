"""No production gateway module reaches Redis through the synchronous client (#428).

Every gateway Redis call runs on the event loop, where a synchronous round
trip stalls every other request, socket and heartbeat. The session and ticket
stores therefore take `redis.asyncio.Redis`; this pins that nothing else
brings the blocking client back.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

GATEWAY = Path(__file__).resolve().parents[1] / "services" / "api_gateway"

EXEMPT = {
    # An offline operator CLI; it never runs inside the gateway's event loop.
    "tenant_cutover.py",
    # The legacy path no gateway app constructs; only tests build it.
    "legacy_session_manager.py",
}

# Where redis-py exposes its synchronous client, and what it calls it there.
SYNC_MODULES = {"redis", "redis.client"}
SYNC_NAMES = {"Redis", "StrictRedis", "client"}


def _sync_redis_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in SYNC_MODULES:
            found += [
                f"{node.module}.{alias.name}" for alias in node.names if alias.name in SYNC_NAMES
            ]
        elif isinstance(node, ast.Import):
            found += [alias.name for alias in node.names if alias.name in SYNC_MODULES]
    return found


@pytest.mark.parametrize(
    "source",
    [
        "from redis import Redis",
        "from redis import StrictRedis",
        "from redis import client",
        "from redis.client import Redis",
        "import redis",
        "import redis.client",
    ],
)
def test_the_guard_recognises_each_way_to_import_the_sync_client(tmp_path, source) -> None:
    module = tmp_path / "module.py"
    module.write_text(source + "\n", encoding="utf-8")

    assert _sync_redis_imports(module) != []


@pytest.mark.parametrize(
    "source",
    [
        "from redis.asyncio import Redis",
        "import redis.asyncio",
        "from redis.exceptions import RedisError",
    ],
)
def test_the_guard_allows_the_async_client_and_the_exceptions(tmp_path, source) -> None:
    module = tmp_path / "module.py"
    module.write_text(source + "\n", encoding="utf-8")

    assert _sync_redis_imports(module) == []


def test_no_production_gateway_module_imports_the_sync_redis_client() -> None:
    offenders = {
        str(path.relative_to(GATEWAY)): names
        for path in sorted(GATEWAY.rglob("*.py"))
        if "tests" not in path.relative_to(GATEWAY).parts
        and path.name not in EXEMPT
        and (names := _sync_redis_imports(path))
    }

    assert offenders == {}


def test_the_exemptions_still_exist() -> None:
    # A renamed exemption would silently stop covering anything.
    assert all((GATEWAY / name).is_file() for name in EXEMPT)


def test_the_tenant_persistence_binding_builds_the_async_client() -> None:
    from redis.asyncio import Redis

    from services.api_gateway import tenant_persistence

    assert tenant_persistence.Redis is Redis
