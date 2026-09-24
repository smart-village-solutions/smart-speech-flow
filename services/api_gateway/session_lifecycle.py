"""Session lifecycle for tenant conversations: create, look up, terminate, list and activate.

The admin and customer routes map what this service returns or raises onto
their status codes and bodies; the decisions themselves live here (#228 task 2.3).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Optional

from .consent_resolution import resolve_consent
from .log_safety import sanitize_log_value
from .session_manager import Session, SessionStatus, TenantSessionManager
from .studio_runtime_client import RuntimeConfiguration, StudioRuntimeClientError
from .studio_runtime_flow import StudioRuntimeFlow
from .studio_runtime_token import StudioTokenError
from .tenant_session import RuntimeConfigurationSnapshot, TenantSessionKey

logger = logging.getLogger(__name__)

# The Contract V1 codes that mean the tenant may not start a session at all.
_TENANT_CONFLICT_CODES = frozenset(
    {"tenant_suspended", "ssf_plugin_inactive", "ssf_tenant_not_ready"}
)
_SUPPORTED_CUSTOMER_LANGUAGES = ("de", "en", "ar", "tr", "ru", "uk", "am", "ti", "ku", "fa")


class SessionNotFoundError(LookupError):
    """No session under the key, or it disappeared while the request ran."""


class NoActiveSessionError(LookupError):
    """The tenant has no pending or active session matching the lookup."""


class SessionTerminatedError(Exception):
    """A terminated session cannot be activated again."""


class TenantConflictError(Exception):
    """Studio says the tenant may not start a session at all."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class Activation:
    session: Session
    already_active: bool


def _safe_session_ref(session_id: Optional[str]) -> str:
    if not session_id:
        return "missing"
    return sha256(session_id.encode("utf-8")).hexdigest()[:12]


class SessionLifecycleService:
    """Owns what the lifecycle routes decide; the routes keep only HTTP mapping."""

    def __init__(self, sessions: TenantSessionManager) -> None:
        self._sessions = sessions

    async def create(self, tenant_id: str, configuration: RuntimeConfiguration) -> Session:
        """A new admin session on the frozen configuration; the manager ends the previous one."""
        return await self._sessions.create_admin_session(
            tenant_id, RuntimeConfigurationSnapshot.from_configuration(configuration)
        )

    def current(self, tenant_id: str, session_id: Optional[str]) -> Session:
        """The tenant's active session, or the named one while it is not terminated.

        Raises:
            NoActiveSessionError: nothing pending or active matches.
            SessionNotFoundError: the match disappeared before it could be read.
            ValueError: several sessions are active and none was named.
        """
        active_session_data = self._sessions.get_active_session(
            session_id=session_id, tenant_id=tenant_id
        )
        if not active_session_data:
            raise NoActiveSessionError
        session = self._sessions.get_session(TenantSessionKey(tenant_id, active_session_data["id"]))
        if session is None:
            raise SessionNotFoundError
        return session

    async def terminate(self, key: TenantSessionKey) -> bool:
        """End the session; False when it had already ended, which changes nothing."""
        session = self._sessions.get_session(key)
        if session is None:
            raise SessionNotFoundError
        if session.status == SessionStatus.TERMINATED:
            return False
        await self._sessions.terminate_session(key, "manual_admin_termination")
        return True

    def history(
        self, tenant_id: str, limit: int
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """The tenant's ended sessions, newest first, and its pending or active ones."""
        history = self._sessions.get_session_history(limit=limit, tenant_id=tenant_id)
        active_sessions = self._sessions.get_active_sessions(tenant_id=tenant_id)
        return history, active_sessions

    async def activate(
        self,
        key: TenantSessionKey,
        customer_language: str,
        data_retention_consent: Optional[bool],
        runtime_flow: StudioRuntimeFlow | None,
        correlation_id: Callable[[], str],
    ) -> Activation:
        """Move a pending session to active, or switch an active one's language.

        `correlation_id` is read only when the live storage policy is fetched,
        so a repeated activation never reads it.

        Raises:
            SessionNotFoundError: no session under the key.
            SessionTerminatedError: the session has ended.
            TenantConflictError: Studio refuses the tenant any session.
        """
        session = self._sessions.get_session(key)
        if session is None:
            raise SessionNotFoundError

        if session.status == SessionStatus.TERMINATED:
            logger.warning(
                "❌ Session bereits beendet | %s",
                sanitize_log_value({"session_ref": _safe_session_ref(key.session_id)}),
            )
            raise SessionTerminatedError

        if session.status == SessionStatus.ACTIVE:
            return await self._reactivate(key, session, customer_language)

        if customer_language not in _SUPPORTED_CUSTOMER_LANGUAGES:
            logger.warning("⚠️ Nicht unterstützte Kundensprache angefordert")
            # Warnung, aber nicht blockieren - der TTS-Service entscheidet final

        # Consent is resolved on this transition alone. `activate_session` is
        # re-entered on every customer language change, and re-resolving there
        # would let a consent-less call overwrite a granted answer.
        live_configuration = await _read_activation_configuration(
            correlation_id, key.tenant_id, runtime_flow
        )
        session.consent_status = resolve_consent(live_configuration, data_retention_consent)

        await self._sessions.activate_session(key, customer_language)

        logger.info(
            "✅ Session erfolgreich aktiviert | %s",
            sanitize_log_value(
                {
                    "session_ref": _safe_session_ref(key.session_id),
                    "customer_language": customer_language,
                }
            ),
        )
        return Activation(session=session, already_active=False)

    async def _reactivate(
        self, key: TenantSessionKey, session: Session, customer_language: str
    ) -> Activation:
        if session.customer_language == customer_language:
            logger.info(
                "ℹ️ Session bereits aktiv - idempotente Antwort | %s",
                sanitize_log_value({"session_ref": _safe_session_ref(key.session_id)}),
            )
            return Activation(session=session, already_active=True)

        logger.info(
            "🔄 Sprache wird aktualisiert | %s",
            sanitize_log_value(
                {
                    "session_ref": _safe_session_ref(key.session_id),
                    "previous_language": session.customer_language,
                    "new_language": customer_language,
                }
            ),
        )
        await self._sessions.activate_session(key, customer_language)
        updated = self._sessions.get_session(key)
        if updated is None:
            raise RuntimeError("session disappeared during a language change")
        return Activation(session=updated, already_active=True)


async def _read_activation_configuration(
    correlation_id: Callable[[], str], tenant_id: str, runtime_flow: StudioRuntimeFlow | None
) -> Optional[RuntimeConfiguration]:
    """Read the live storage policy for one activation.

    Returns `None` for every failure except a tenant conflict, which is raised
    because no session may start. Deliberately not routed through
    `RuntimePolicyGate`: that records discarded conversation content, and
    activation writes none.

    Raises:
        TenantConflictError: the tenant may not start a session.
    """
    # Read before the flow check, so a malformed header fails whether or not
    # Studio is configured.
    request_correlation_id = correlation_id()
    if runtime_flow is None:
        return None
    try:
        return await runtime_flow.client.fetch(tenant_id, request_correlation_id)
    except (StudioRuntimeClientError, StudioTokenError) as error:
        code = getattr(error, "code", None)
        if code in _TENANT_CONFLICT_CODES:
            raise TenantConflictError(code) from None
        return None
