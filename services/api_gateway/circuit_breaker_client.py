"""Health monitoring and status reporting for the AI services.

This module used to carry ``call_asr_service``, ``call_translation_service``
and ``call_tts_service``. They had no callers outside their own tests and
could not have served the pipeline: they hardcoded ``http://<service>:8000``,
ignoring the ``DOCKER_COMPOSE=0`` mapping to localhost, returned field names
the pipeline does not read, and were bounded by the health-check timeout
rather than the inference timeout. Production calls go through
:mod:`.ai_service_client` (#219).

What remains is the lifespan's monitoring control and the read-only status
methods behind the ``/api/health/*`` and ``/api/circuit-breaker/*`` routes.
"""

import asyncio
import logging
from typing import Any, Dict

from .graceful_degradation import graceful_degradation_manager
from .service_health import service_health_manager

logger = logging.getLogger(__name__)


class CircuitBreakerServiceClient:
    """Monitoring control and read-only status for the AI services.

    Holds no HTTP session of its own any more: the only requests it used to
    make were the three call paths that nothing called. The health checks
    have always had their own session in :mod:`.service_health`.
    """

    async def get_health_status(self) -> Dict[str, Any]:
        """Gesamter Health Status aller Services"""
        await asyncio.sleep(0)
        return service_health_manager.get_overall_health()

    async def get_service_status(self, service_name: str) -> Dict[str, Any]:
        """Health Status für einzelnen Service"""
        await asyncio.sleep(0)
        return service_health_manager.get_service_health(service_name)

    async def get_degradation_status(self) -> Dict[str, Any]:
        """Aktueller Degradation Status"""
        await asyncio.sleep(0)
        return graceful_degradation_manager.get_degradation_status()

    async def start_health_monitoring(self):
        """Startet Health Monitoring"""
        await service_health_manager.start_monitoring()
        logger.info("🚀 Circuit Breaker Health Monitoring gestartet")

    async def stop_health_monitoring(self):
        """Stoppt Health Monitoring"""
        await service_health_manager.stop_monitoring()
        logger.info("🛑 Circuit Breaker Health Monitoring gestoppt")


# Globale Circuit Breaker Service Client Instanz. Adapter until PR5 (#228).
circuit_breaker_client = CircuitBreakerServiceClient()
