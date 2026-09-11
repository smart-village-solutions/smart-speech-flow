"""Application-lifespan ownership of tenant session and ticket persistence."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

try:
    from redis import Redis
except ImportError:  # pragma: no cover - exercised only in stripped deployments
    Redis = None  # type: ignore[assignment]

from .realtime_ticket import realtime_ticket_store
from .session_manager import SessionManager, session_manager
from .session_store import RedisTenantSessionStore, TenantSessionStore

logger = logging.getLogger(__name__)


class TenantPersistenceUnavailable(RuntimeError):
    """Production tenant state cannot be configured safely."""


def _reset_runtime(manager: SessionManager) -> None:
    websocket_manager = manager.websocket_manager
    manager.reset()
    if websocket_manager is not None:
        manager.register_websocket_manager(websocket_manager)


@dataclass(slots=True)
class TenantPersistenceBinding:
    """Restore process-wide development backends after a lifespan exits."""

    redis: Any
    manager: SessionManager
    previous_store: TenantSessionStore | None
    previous_ticket_backend: Any
    previous_ticket_namespace: str

    def close(self) -> None:
        self.manager.store = self.previous_store
        self.manager.tenant_mode = self.previous_store is not None
        _reset_runtime(self.manager)
        realtime_ticket_store.redis = self.previous_ticket_backend
        realtime_ticket_store.namespace = self.previous_ticket_namespace
        close = getattr(self.redis, "close", None)
        if callable(close):
            close()


def _redis_namespace() -> str:
    namespace = os.environ.get("REDIS_NAMESPACE", "ssf").strip()
    if not namespace or any(character.isspace() for character in namespace):
        raise TenantPersistenceUnavailable("tenant persistence configuration invalid")
    return namespace


def configure_tenant_persistence() -> TenantPersistenceBinding | None:
    """Bind both v2 stores to one verified Redis connection.

    Local processes without a configured Redis URL retain the explicit memory
    implementations. A production process must configure Redis, and any
    configured process aborts startup if the client cannot be constructed or
    verified. There is intentionally no production fallback to process memory.
    """

    deployment = os.environ.get("SSF_DEPLOYMENT_ENV", "unknown").strip().casefold()
    redis_url = os.environ.get("REDIS_URL", "").strip()
    if not redis_url:
        if deployment == "production":
            raise TenantPersistenceUnavailable(
                "tenant persistence configuration unavailable"
            )
        return None
    if Redis is None:
        raise TenantPersistenceUnavailable("tenant persistence client unavailable")

    namespace = _redis_namespace()
    try:
        redis = Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        redis.ping()
    except Exception:
        raise TenantPersistenceUnavailable(
            "tenant persistence connection unavailable"
        ) from None

    binding = TenantPersistenceBinding(
        redis=redis,
        manager=session_manager,
        previous_store=session_manager.store,
        previous_ticket_backend=realtime_ticket_store.redis,
        previous_ticket_namespace=realtime_ticket_store.namespace,
    )
    session_manager.store = RedisTenantSessionStore(redis, namespace=namespace)
    session_manager.tenant_mode = True
    _reset_runtime(session_manager)
    realtime_ticket_store.redis = redis
    realtime_ticket_store.namespace = namespace
    session_manager.rehydrate_tenant_sessions()
    logger.info("tenant_redis_persistence_ready")
    return binding
