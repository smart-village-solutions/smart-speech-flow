"""Application-lifespan ownership of the tenant Redis connection."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

try:
    from redis.asyncio import BlockingConnectionPool, Redis
    from redis.exceptions import RedisError
except ImportError:  # pragma: no cover - exercised only in stripped deployments
    BlockingConnectionPool = None  # type: ignore[assignment,misc]
    Redis = None  # type: ignore[assignment]

    class RedisError(Exception):  # type: ignore[no-redef]
        pass


logger = logging.getLogger(__name__)

# redis-py's async default pool raises the moment every connection is in use.
# This one makes a command wait for a free connection instead, and no longer
# than a command on the wire may take, so a stalled Redis fails both alike.
_MAX_CONNECTIONS = 100
_SOCKET_TIMEOUT_SECONDS = 5


class TenantPersistenceUnavailable(RuntimeError):
    """Production tenant state cannot be configured safely."""


@dataclass(slots=True)
class TenantPersistenceBinding:
    """The verified connection the app's session and ticket stores are built on."""

    redis: Any
    namespace: str

    async def close(self) -> None:
        await self.redis.aclose()


def _redis_namespace() -> str:
    namespace = os.environ.get("REDIS_NAMESPACE", "ssf").strip()
    if not namespace or any(character.isspace() for character in namespace):
        raise TenantPersistenceUnavailable("tenant persistence configuration invalid")
    return namespace


async def configure_tenant_persistence() -> TenantPersistenceBinding | None:
    """Verify the one Redis connection the v2 session and ticket stores share.

    Local processes without a configured Redis URL retain the explicit memory
    implementations. A production process must configure Redis, and any
    configured process aborts startup if the client cannot be constructed or
    verified. There is intentionally no production fallback to process memory.
    """

    deployment = os.environ.get("SSF_DEPLOYMENT_ENV", "unknown").strip().casefold()
    redis_url = os.environ.get("REDIS_URL", "").strip()
    if not redis_url:
        if deployment == "production":
            raise TenantPersistenceUnavailable("tenant persistence configuration unavailable")
        return None
    if Redis is None or BlockingConnectionPool is None:
        raise TenantPersistenceUnavailable("tenant persistence client unavailable")

    namespace = _redis_namespace()
    try:
        pool = BlockingConnectionPool.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=_SOCKET_TIMEOUT_SECONDS,
            socket_timeout=_SOCKET_TIMEOUT_SECONDS,
            max_connections=_MAX_CONNECTIONS,
            timeout=_SOCKET_TIMEOUT_SECONDS,
        )
        # from_pool hands the pool to the client, so closing one closes both.
        redis = Redis.from_pool(pool)
    except (RedisError, OSError, ValueError):
        # ValueError: from_url refusing a malformed URL. `from None` keeps the URL,
        # which can carry credentials, out of the startup log.
        raise TenantPersistenceUnavailable("tenant persistence connection unavailable") from None
    try:
        await redis.ping()
    except (RedisError, OSError, ValueError):
        await redis.aclose()
        raise TenantPersistenceUnavailable("tenant persistence connection unavailable") from None

    logger.info("tenant_redis_persistence_ready")
    return TenantPersistenceBinding(redis=redis, namespace=namespace)
