"""Shared session cache, lifecycle telemetry and content-retention behaviour."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar

from .quality_telemetry_schema import SessionLifecyclePhase, SessionTerminationReason
from .session_models import Session, SessionStatus, _env_flag, _session_duration_ms
from .session_ports import SessionSockets
from .session_pseudonym import MISSING_TENANT_REFERENCE, SessionPseudonymizer, tenant_ref
from .tenant_session import TenantSessionKey

logger = logging.getLogger(__name__)
KeyT = TypeVar("KeyT")


class SessionManagerBase(Generic[KeyT]):
    """The session cache, lifecycle telemetry and content sweep both managers share."""

    quality_telemetry: Optional[Any] = None

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        pseudonymizer: Optional[SessionPseudonymizer],
    ) -> None:
        self.allow_parallel_sessions: bool = _env_flag("SSF_ALLOW_PARALLEL_SESSIONS", False)
        self.clock = clock
        self.pseudonymizer = pseudonymizer or SessionPseudonymizer.from_environment()
        self.sessions: Dict[KeyT, Session] = {}
        self.websocket_manager: Optional[SessionSockets[KeyT]] = None

    def attach_quality_telemetry(self, telemetry: Optional[Any]) -> None:
        """Wired by the gateway's lifespan; None detaches it on teardown."""
        self.quality_telemetry = telemetry

    def register_websocket_manager(self, manager: SessionSockets[KeyT]) -> None:
        """Register the websocket manager for bidirectional cleanup."""
        self.websocket_manager = manager

    def _emit_lifecycle(
        self,
        session: Session,
        phase: SessionLifecyclePhase,
        reason: SessionTerminationReason = SessionTerminationReason.NONE,
    ) -> None:
        """Never raises. Telemetry must not decide whether a session opens."""
        telemetry = self.quality_telemetry
        if telemetry is None:
            return
        # A recorded session's events say nothing that dates or sizes it: duration
        # and count would join its random reference to its keyed one (spec §5.5).
        recorded = self.pseudonymizer.is_recorded(session.id)
        try:
            telemetry.emit_session_lifecycle(
                session_ref=self.pseudonymizer.reference(session.id),
                tenant_ref=(
                    tenant_ref(session.tenant_id) if session.tenant_id else MISSING_TENANT_REFERENCE
                ),
                phase=phase,
                termination_reason=reason,
                session_duration_ms=0 if recorded else _session_duration_ms(session),
                message_count=0 if recorded else session.message_count,
            )
        except Exception:  # telemetry must never reach the caller
            logger.warning("Session quality telemetry failed", exc_info=True)

    async def _persist_swept_session(self, session: Session) -> None:
        """Write back a session the sweep changed.

        Called only when something actually changed: a sweep that rewrote every
        session on every pass would turn an hourly maintenance task into
        continuous write amplification against Redis.
        """
        raise NotImplementedError

    def _delete_session_audio(self, key: TenantSessionKey) -> None:
        """Delete every delivery audio file of the session.

        Only a tenant session has any, so only `TenantSessionManager` has an
        audio store to delete them from.
        """
        raise NotImplementedError

    async def sweep_expired_content(self, now: datetime) -> Dict[str, int]:
        """Strip a session that outlived its maximum lifetime without ending.

        A session that ends strips its own content at termination; this pass
        catches one whose termination never ran, so no conversation's content
        outlasts the session's lifetime.

        Args:
            now: The moment to measure the session's age against.

        Returns:
            Counts of the messages removed, and of the sessions whose removal
            could not be saved and stays for the next pass.
        """
        removed = 0
        failed = 0

        # Persistence callbacks may change the cache while this pass runs.
        for session in self.sessions.copy().values():
            # A terminated record is immutable in the store -- SAVE_SESSION_LUA
            # refuses every change to one -- and was stripped when it ended.
            if session.status is SessionStatus.TERMINATED:
                continue
            if now - session.created_at < timedelta(hours=session.maximum_lifetime_hours):
                continue
            try:
                removed += await self._sweep_session_content(session)
            except Exception:  # noqa: BLE001 - one session must not stop the pass
                logger.warning(
                    "content_sweep_failed",
                    extra={"session_ref": self.pseudonymizer.reference(session.id)},
                )
                failed += 1

        return {"removed": removed, "failed": failed}

    async def _sweep_session_content(self, session: Session) -> int:
        if not session.messages:
            return 0
        previous = session.messages
        removed = len(previous)
        session.messages = []
        try:
            await self._persist_swept_session(session)
        except Exception:
            # A termination that committed meanwhile stripped the record, and that stands.
            if session.status is not SessionStatus.TERMINATED:
                # Messages appended while the write was pending are kept too.
                session.messages = previous + session.messages
            raise
        # `Session.key` raises without a tenant, and a legacy session has no audio.
        if session.tenant_id is not None:
            self._delete_session_audio(session.key)
        return removed

    def get_sessions_requiring_timeout_check(self) -> List[Session]:
        """Return sessions requiring timeout checks."""
        return [
            session
            for session in self.sessions.values()
            if session.status in [SessionStatus.ACTIVE, SessionStatus.PENDING]
        ]
