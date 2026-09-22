"""Service-mode tracking for the AI services.

Reports how much of the pipeline is currently usable, derived from the circuit
breakers in :mod:`.service_health`. Backs ``GET /api/health/degradation``.

This module used to be much larger. It carried a response cache, a request
queue and four fallback strategies, all reachable only through
``handle_service_failure`` -- which had no production caller, and whose first
two strategies invented results: one returned success for four services that
do not exist in this repository, the other returned a placeholder transcript
and the untranslated source text labelled as a translation. #219 put the real
calls behind the breakers and removed the rest; a failed call now surfaces as
a pipeline error rather than a fabricated success.

Autor: Smart Village Solutions
Datum: November 2025
"""

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ServiceMode(Enum):
    """Service Betriebsmodi"""

    FULL = "full"  # Alle Services verfügbar
    DEGRADED = "degraded"  # Eingeschränkte Funktionalität
    MINIMAL = "minimal"  # Nur Basis-Features
    OFFLINE = "offline"  # Kein Service verfügbar


class GracefulDegradationManager:
    """Tracks how much of the pipeline is currently usable."""

    def __init__(self):
        self.current_mode = ServiceMode.FULL
        self.mode_history: List[Dict] = []

        logger.info("🛡️ Graceful Degradation Manager initialisiert")

    def apply_service_states(self, usable: Dict[str, bool]) -> None:
        """Recomputes the reported mode from which services are callable.

        Derived rather than accumulated. The previous implementation only ever
        made the mode worse -- its recovery branch was a literal ``pass`` -- so
        a single failure pinned the endpoint to DEGRADED for the life of the
        process. Recomputing means recovery needs no separate path and cannot
        be forgotten.

        ``usable`` maps each service to whether its breaker has a *verified*
        path to the service, which means CLOSED. A half-open breaker will
        admit a probe but has not been shown to work yet, and reporting full
        service on the strength of an unverified probe made the mode flap to
        ``full`` during every recovery cycle of a real outage.
        """
        if not usable:
            return

        unusable = sorted(name for name, ok in usable.items() if not ok)
        if not unusable:
            new_mode = ServiceMode.FULL
        elif len(unusable) >= len(usable):
            new_mode = ServiceMode.OFFLINE
        elif len(unusable) == 1:
            new_mode = ServiceMode.DEGRADED
        else:
            new_mode = ServiceMode.MINIMAL

        self._record_mode(new_mode, trigger=", ".join(unusable) or "recovery")

    def _record_mode(self, new_mode: ServiceMode, *, trigger: str) -> None:
        old_mode = self.current_mode
        if old_mode == new_mode:
            return

        self.current_mode = new_mode
        self.mode_history.append(
            {
                "timestamp": utc_now().isoformat(),
                "old_mode": old_mode.value,
                "new_mode": new_mode.value,
                "trigger_service": trigger,
                "is_failure": new_mode is not ServiceMode.FULL,
            }
        )
        logger.warning(f"🔄 Service Mode: {old_mode.value} → {new_mode.value} (Trigger: {trigger})")

    def get_degradation_status(self) -> Dict[str, Any]:
        """Aktueller Degradation Status"""
        return {
            "current_mode": self.current_mode.value,
            "mode_history": self.mode_history[-10:],  # Letzte 10 Mode Changes
        }


# Globale Graceful Degradation Manager Instanz
graceful_degradation_manager = GracefulDegradationManager()
