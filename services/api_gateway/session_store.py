"""Tenant-scoped in-memory and Redis persistence for conversation sessions."""

from __future__ import annotations

import hmac
import json
import logging
from typing import TYPE_CHECKING, Any, Protocol

from .tenant_session import TenantSessionKey

if TYPE_CHECKING:
    from .session_manager import Session


logger = logging.getLogger(__name__)


CREATE_SESSION_LUA = """
if redis.call('EXISTS', KEYS[3]) == 1 then return 0 end
redis.call('SET', KEYS[1], ARGV[1])
redis.call('SADD', KEYS[2], ARGV[2])
redis.call('SET', KEYS[3], ARGV[3])
redis.call('SADD', KEYS[4], ARGV[2])
return 1
"""

SAVE_SESSION_LUA = """
local current_session = redis.call('GET', KEYS[1])
local current_join = redis.call('GET', KEYS[2])
if not current_session or not current_join then return 0 end
local current_decoded, current = pcall(cjson.decode, current_session)
local proposed_decoded, proposed = pcall(cjson.decode, ARGV[1])
if not current_decoded or not proposed_decoded then return 0 end
if current['id'] ~= ARGV[2] or current['tenant_id'] ~= ARGV[3] then return 0 end
if proposed['id'] ~= ARGV[2] or proposed['tenant_id'] ~= ARGV[3] then return 0 end
if current['status'] == 'terminated' then
  if current_join ~= ARGV[5] then return 0 end
  if redis.call('SISMEMBER', KEYS[3], ARGV[2]) ~= 0 then return 0 end
  if current_session ~= ARGV[1] then return 0 end
  return 1
end
if current_join ~= ARGV[4] then return 0 end
if redis.call('SISMEMBER', KEYS[3], ARGV[2]) ~= 1 then return 0 end
if proposed['status'] == 'terminated' then return 0 end
redis.call('SET', KEYS[1], ARGV[1])
return 1
"""

TERMINATE_SESSION_LUA = """
local current_join = redis.call('GET', KEYS[3])
if current_join == ARGV[3] then
  redis.call('SET', KEYS[1], ARGV[1])
  redis.call('SREM', KEYS[2], ARGV[2])
  redis.call('SET', KEYS[3], ARGV[4])
  return 1
end
if current_join ~= ARGV[4] then return 0 end
if redis.call('SISMEMBER', KEYS[2], ARGV[2]) ~= 0 then return 0 end
local current_session = redis.call('GET', KEYS[1])
if not current_session then return 0 end
local decoded, payload = pcall(cjson.decode, current_session)
if not decoded then return 0 end
if payload['id'] ~= ARGV[2] then return 0 end
if payload['tenant_id'] ~= ARGV[5] then return 0 end
if payload['status'] ~= 'terminated' then return 0 end
return 2
"""


class SessionStoreConsistencyError(RuntimeError):
    """A security-sensitive store mutation observed inconsistent state."""


class TenantSessionStore(Protocol):
    def create(self, session: Session) -> bool:
        raise NotImplementedError

    def save(self, session: Session) -> None:
        raise NotImplementedError

    def load(self, key: TenantSessionKey) -> Session | None:
        raise NotImplementedError

    def resolve_join(self, session_id: str) -> TenantSessionKey | None:
        raise NotImplementedError

    def list_for_tenant(self, tenant_id: str) -> list[Session]:
        raise NotImplementedError

    def list_active(self) -> list[Session]:
        raise NotImplementedError

    def terminate(self, session: Session) -> Session:
        raise NotImplementedError


def session_key(namespace: str, key: TenantSessionKey) -> str:
    return (
        f"{namespace}:v2:tenant:{key.redis_tenant_component}:"
        f"session:{key.session_id}"
    )


def tenant_sessions_key(namespace: str, tenant_id: str) -> str:
    key = TenantSessionKey(tenant_id, "index")
    return f"{namespace}:v2:tenant:{key.redis_tenant_component}:sessions"


def tenant_active_sessions_key(namespace: str, tenant_id: str) -> str:
    key = TenantSessionKey(tenant_id, "index")
    return f"{namespace}:v2:tenant:{key.redis_tenant_component}:active-admin"


def join_key(namespace: str, session_id: str) -> str:
    TenantSessionKey("validation", session_id)
    return f"{namespace}:v2:join:{session_id}"


def _join_payload(key: TenantSessionKey, *, active: bool) -> str:
    return json.dumps(
        {
            "active": active,
            "session_id": key.session_id,
            "tenant_id": key.tenant_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _decode_join(raw: str | None) -> tuple[TenantSessionKey, bool] | None:
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict) or not isinstance(payload["active"], bool):
            return None
        key = TenantSessionKey(payload["tenant_id"], payload["session_id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return key, payload["active"]


def _same_key(left: TenantSessionKey, right: TenantSessionKey) -> bool:
    return hmac.compare_digest(left.tenant_id, right.tenant_id) and hmac.compare_digest(
        left.session_id, right.session_id
    )


class MemoryTenantSessionStore:
    """Process-local implementation with the same collision rules as Redis."""

    def __init__(self) -> None:
        self._sessions: dict[TenantSessionKey, Session] = {}
        self._joins: dict[str, tuple[TenantSessionKey, bool]] = {}

    def clear(self) -> None:
        self._sessions.clear()
        self._joins.clear()

    def create(self, session: Session) -> bool:
        if session.id in self._joins:
            return False
        self._sessions[session.key] = session
        self._joins[session.id] = (session.key, True)
        return True

    def save(self, session: Session) -> None:
        if session.key not in self._sessions:
            raise SessionStoreConsistencyError("session does not exist")
        self._sessions[session.key] = session

    def load(self, key: TenantSessionKey) -> Session | None:
        session = self._sessions.get(key)
        join = self._joins.get(key.session_id)
        if session is None or join is None or not _same_key(session.key, key):
            return None
        join_key_value, active = join
        expected_active = session.status.value != "terminated"
        if not _same_key(join_key_value, key) or active is not expected_active:
            return None
        return session

    def resolve_join(self, session_id: str) -> TenantSessionKey | None:
        join = self._joins.get(session_id)
        if join is None:
            return None
        key, active = join
        if not active or self.load(key) is None:
            return None
        return key

    def list_for_tenant(self, tenant_id: str) -> list[Session]:
        return [
            session
            for key in tuple(self._sessions)
            if hmac.compare_digest(key.tenant_id, tenant_id)
            and (session := self.load(key)) is not None
        ]

    def list_active(self) -> list[Session]:
        return [
            session
            for key in tuple(self._sessions)
            if (session := self.load(key)) is not None
            and session.status.value != "terminated"
        ]

    def terminate(self, session: Session) -> Session:
        join = self._joins.get(session.id)
        if join is None or not _same_key(join[0], session.key):
            raise SessionStoreConsistencyError("join index does not match session")
        if not join[1]:
            persisted = self._sessions.get(session.key)
            if persisted is None or persisted.status.value != "terminated":
                raise SessionStoreConsistencyError(
                    "terminal join index does not match session"
                )
            return persisted
        self._sessions[session.key] = session
        self._joins[session.id] = (session.key, False)
        return session


class RedisTenantSessionStore:
    """Redis v2 implementation with atomic create and terminate mutations."""

    def __init__(self, redis: Any, *, namespace: str = "ssf") -> None:
        self.redis = redis
        self.namespace = namespace

    def create(self, session: Session) -> bool:
        key = session.key
        result = self.redis.eval(
            CREATE_SESSION_LUA,
            4,
            session_key(self.namespace, key),
            tenant_sessions_key(self.namespace, key.tenant_id),
            join_key(self.namespace, key.session_id),
            tenant_active_sessions_key(self.namespace, key.tenant_id),
            self._session_payload(session),
            key.session_id,
            _join_payload(key, active=True),
        )
        return result == 1

    def save(self, session: Session) -> None:
        key = session.key
        result = self.redis.eval(
            SAVE_SESSION_LUA,
            3,
            session_key(self.namespace, key),
            join_key(self.namespace, key.session_id),
            tenant_active_sessions_key(self.namespace, key.tenant_id),
            self._session_payload(session),
            key.session_id,
            key.tenant_id,
            _join_payload(key, active=True),
            _join_payload(key, active=False),
        )
        if result != 1:
            raise SessionStoreConsistencyError("session lifecycle does not permit save")

    def load(self, key: TenantSessionKey) -> Session | None:
        raw_session = self.redis.get(session_key(self.namespace, key))
        raw_join = self.redis.get(join_key(self.namespace, key.session_id))
        if raw_session is None:
            return None
        try:
            from .session_manager import Session

            session = Session.from_dict(json.loads(raw_session))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            logger.warning(
                "tenant_session_record_quarantined",
                extra={"tenant_ref": key.tenant_ref},
            )
            return None
        decoded_join = _decode_join(raw_join)
        expected_active = session.status.value != "terminated"
        if (
            decoded_join is None
            or not _same_key(session.key, key)
            or not _same_key(decoded_join[0], key)
            or decoded_join[1] is not expected_active
        ):
            logger.warning(
                "tenant_session_record_quarantined",
                extra={"tenant_ref": key.tenant_ref},
            )
            return None
        return session

    def resolve_join(self, session_id: str) -> TenantSessionKey | None:
        decoded = _decode_join(self.redis.get(join_key(self.namespace, session_id)))
        if decoded is None or not decoded[1]:
            return None
        key = decoded[0]
        return key if self.load(key) is not None else None

    def list_for_tenant(self, tenant_id: str) -> list[Session]:
        sessions: list[Session] = []
        for session_id in self.redis.smembers(
            tenant_sessions_key(self.namespace, tenant_id)
        ):
            key = TenantSessionKey(tenant_id, session_id)
            if session := self.load(key):
                sessions.append(session)
        return sessions

    def list_active(self) -> list[Session]:
        """Load the installation's active indexes only during startup.

        Request handlers continue to use the tenant-specific index. The global
        scan exists solely to rebuild process-local timeout and replacement
        enforcement after a gateway restart.
        """

        sessions: list[Session] = []
        pattern = f"{self.namespace}:v2:tenant:*:active-admin"
        for raw_active_key in self.redis.scan_iter(match=pattern):
            active_key = (
                raw_active_key.decode("utf-8")
                if isinstance(raw_active_key, bytes)
                else raw_active_key
            )
            for raw_session_id in self.redis.smembers(active_key):
                session_id = (
                    raw_session_id.decode("utf-8")
                    if isinstance(raw_session_id, bytes)
                    else raw_session_id
                )
                record_key = active_key.removesuffix(":active-admin")
                raw_session = self.redis.get(f"{record_key}:session:{session_id}")
                try:
                    from .session_manager import Session

                    session = Session.from_dict(json.loads(raw_session))
                    key = session.key
                except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                    raise SessionStoreConsistencyError(
                        "active session index does not match session"
                    ) from None
                if (
                    session.id != session_id
                    or tenant_active_sessions_key(self.namespace, key.tenant_id)
                    != active_key
                    or session_key(self.namespace, key)
                    != f"{record_key}:session:{session_id}"
                ):
                    raise SessionStoreConsistencyError(
                        "active session index does not match session"
                    )
                loaded = self.load(key)
                if loaded is None or loaded.status.value == "terminated":
                    raise SessionStoreConsistencyError(
                        "active session index does not match session"
                    )
                sessions.append(loaded)
        return sessions

    def terminate(self, session: Session) -> Session:
        key = session.key
        result = self.redis.eval(
            TERMINATE_SESSION_LUA,
            3,
            session_key(self.namespace, key),
            tenant_active_sessions_key(self.namespace, key.tenant_id),
            join_key(self.namespace, key.session_id),
            self._session_payload(session),
            key.session_id,
            _join_payload(key, active=True),
            _join_payload(key, active=False),
            key.tenant_id,
        )
        if result == 1:
            return session
        if result == 2:
            persisted = self.load(key)
            if persisted is not None and persisted.status.value == "terminated":
                return persisted
        raise SessionStoreConsistencyError("join index does not match session")

    @staticmethod
    def _session_payload(session: Session) -> str:
        return json.dumps(
            session.to_dict(include_messages=True),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
