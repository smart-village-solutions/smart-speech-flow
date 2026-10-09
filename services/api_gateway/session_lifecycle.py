"""Session lifecycle for tenant conversations: create, look up, terminate, list and activate.

The admin and customer routes map what this service returns or raises onto
their status codes and bodies; the decisions themselves live here (#228 task 2.3).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Optional

from .consent import ConsentStatus
from .consent_resolution import resolve_consent
from .keyed_locks import KeyedLocks
from .log_safety import safe_session_ref, sanitize_log_value
from .session_manager import TenantSessionManager
from .session_models import Session, SessionStatus
from .studio_runtime_flow import StudioRuntimeFlow
from .studio_runtime_token import StudioTokenError
from .studio_runtime_v2_client import TENANT_CONFLICT_CODES, StudioRuntimeV2ClientError
from .studio_v2 import RuntimePolicy
from .tenant_session import TenantSessionKey

logger = logging.getLogger(__name__)

# The Studio codes that mean the tenant may not start a session at all.
_SUPPORTED_CUSTOMER_LANGUAGES = ("de", "en", "ar", "tr", "ru", "uk", "am", "ti", "ku", "fa")
# A logged language is looked up here, so the value written to the log is one of these
# constants and never the code the request carried.
_LOGGED_LANGUAGES = {code: code for code in _SUPPORTED_CUSTOMER_LANGUAGES}


def _logged_language(code: Optional[str]) -> str:
    return _LOGGED_LANGUAGES.get(code or "", "unsupported")


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


class SessionLifecycleService:
    """Owns what the lifecycle routes decide; the routes keep only HTTP mapping."""

    def __init__(self, sessions: TenantSessionManager) -> None:
        self._sessions = sessions
        # Consent is captured across an awaited Studio read and an awaited save;
        # a second join of the same session must wait and find it active.
        self._activation_locks: KeyedLocks[TenantSessionKey] = KeyedLocks()

    async def create(
        self,
        tenant_id: str,
        configuration_revision: str,
        *,
        owner_ref: str,
    ) -> Session:
        """A new admin session on the read's revision; it ends the owner's previous one."""
        return await self._sessions.create_admin_session(
            tenant_id, configuration_revision, owner_ref=owner_ref
        )

    async def current(
        self, tenant_id: str, session_id: Optional[str], *, owner_ref: str
    ) -> Session:
        """The admin's active session, or the named one while it is not terminated.

        Named or not, only the requesting admin's own sessions count (#476).

        Raises:
            NoActiveSessionError: nothing pending or active matches.
            SessionNotFoundError: the match disappeared before it could be read.
            ValueError: several sessions are active and none was named.
        """
        active_session_data = await self._sessions.get_active_session(
            session_id=session_id,
            tenant_id=tenant_id,
            owner_ref=owner_ref,
        )
        if not active_session_data:
            raise NoActiveSessionError
        session = await self._sessions.get_session(
            TenantSessionKey(tenant_id, active_session_data["id"])
        )
        if session is None:
            raise SessionNotFoundError
        return session

    async def terminate(self, key: TenantSessionKey) -> bool:
        """End the session; False when it had already ended, which changes nothing."""
        session = await self._sessions.get_session(key)
        if session is None:
            raise SessionNotFoundError
        if session.status == SessionStatus.TERMINATED:
            return False
        await self._sessions.terminate_session(key, "manual_admin_termination")
        return True

    async def history(
        self, tenant_id: str, limit: int, *, owner_ref: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """The admin's ended sessions, newest first, and their pending or active ones."""
        history = await self._sessions.get_session_history(
            limit=limit, tenant_id=tenant_id, owner_ref=owner_ref
        )
        active_sessions = await self._sessions.get_active_sessions(
            tenant_id=tenant_id, owner_ref=owner_ref
        )
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
        async with self._activation_locks.hold(key):
            return await self._activate(
                key, customer_language, data_retention_consent, runtime_flow, correlation_id
            )

    async def _activate(
        self,
        key: TenantSessionKey,
        customer_language: str,
        data_retention_consent: Optional[bool],
        runtime_flow: StudioRuntimeFlow | None,
        correlation_id: Callable[[], str],
    ) -> Activation:
        session = await self._sessions.get_session(key)
        if session is None:
            raise SessionNotFoundError

        if session.status == SessionStatus.TERMINATED:
            logger.warning(
                "❌ Session bereits beendet | %s",
                sanitize_log_value({"session_ref": safe_session_ref(key.session_id)}),
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
        live_policy = await _read_activation_policy(correlation_id, key.tenant_id, runtime_flow)
        # The session may have been ended while Studio answered.
        if await self._sessions.get_session_status(key) == SessionStatus.TERMINATED:
            raise SessionTerminatedError
        session.consent_status = resolve_consent(live_policy, data_retention_consent)
        # The retention the guest agreed to, from the same read; it never changes after.
        if session.consent_status is ConsentStatus.GRANTED and live_policy is not None:
            session.consent_retention_hours = live_policy.retention_hours
            session.consent_configuration_revision = live_policy.configuration_revision

        await self._sessions.activate_session(key, customer_language)

        logger.info(
            "✅ Session erfolgreich aktiviert | %s",
            sanitize_log_value(
                {
                    "session_ref": safe_session_ref(key.session_id),
                    "customer_language": _logged_language(customer_language),
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
                sanitize_log_value({"session_ref": safe_session_ref(key.session_id)}),
            )
            return Activation(session=session, already_active=True)

        logger.info(
            "🔄 Sprache wird aktualisiert | %s",
            sanitize_log_value(
                {
                    "session_ref": safe_session_ref(key.session_id),
                    "previous_language": _logged_language(session.customer_language),
                    "new_language": _logged_language(customer_language),
                }
            ),
        )
        await self._sessions.activate_session(key, customer_language)
        updated = await self._sessions.get_session(key)
        if updated is None:
            raise RuntimeError("session disappeared during a language change")
        return Activation(session=updated, already_active=True)


async def _read_activation_policy(
    correlation_id: Callable[[], str], tenant_id: str, runtime_flow: StudioRuntimeFlow | None
) -> Optional[RuntimePolicy]:
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
        read = await runtime_flow.reads("activation").fetch(tenant_id, request_correlation_id)
    except (StudioRuntimeV2ClientError, StudioTokenError) as error:
        code = getattr(error, "code", None)
        if code in TENANT_CONFLICT_CODES:
            raise TenantConflictError(code) from None
        return None
    return read.policy
