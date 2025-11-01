"""
Service Health Manager für Smart Speech Flow Backend
===================================================

Zentrale Verwaltung und Überwachung aller Mikroservices:
- ASR (Automatic Speech Recognition) Service
- Translation Service
- TTS (Text-to-Speech) Service
- Health Check Monitoring
- Circuit Breaker Integration

Autor: Smart Village Solutions
Datum: November 2025
Version: 1.0
"""

import asyncio
import aiohttp
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging

from .circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerFactory,
    CircuitBreakerConfig,
    CircuitState,
    CircuitBreakerOpenException
)

logger = logging.getLogger(__name__)


@dataclass
class ServiceEndpoint:
    """Service Endpoint Configuration"""
    name: str
    base_url: str
    health_path: str = "/health"
    timeout: float = 5.0

    @property
    def health_url(self) -> str:
        return f"{self.base_url.rstrip('/')}{self.health_path}"


@dataclass
class ServiceStatus:
    """Service Status Information"""
    name: str
    is_healthy: bool = False
    last_check: Optional[datetime] = None
    response_time: float = 0.0
    error_message: Optional[str] = None
    status_code: Optional[int] = None

    # Extended Health Info
    uptime: Optional[str] = None
    version: Optional[str] = None
    memory_usage: Optional[Dict] = None
    active_connections: Optional[int] = None


class ServiceHealthManager:
    """
    Zentrale Service Health Verwaltung

    Features:
    - Periodische Health Checks für alle Services
    - Circuit Breaker Integration
    - Service Discovery und Failover
    - Health Metrics und Monitoring
    - Graceful Degradation Support
    """

    def __init__(self):
        # Service Endpoints
        self.services: Dict[str, ServiceEndpoint] = {}
        self.service_status: Dict[str, ServiceStatus] = {}

        # Circuit Breakers
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}

        # Health Check Configuration
        self.check_interval = 30.0  # Sekunden
        self.is_monitoring = False
        self.health_check_task: Optional[asyncio.Task] = None

        # HTTP Session für Health Checks
        self.session: Optional[aiohttp.ClientSession] = None

        # Default Service Configuration
        self._setup_default_services()

        logger.info("🏥 Service Health Manager initialisiert")

    def _setup_default_services(self):
        """Setup Standard Services für Smart Speech Flow"""
        # ASR Service
        self.register_service(ServiceEndpoint(
            name="asr",
            base_url="http://asr:8001",
            health_path="/health",
            timeout=10.0  # ASR kann länger dauern
        ))

        # Translation Service
        self.register_service(ServiceEndpoint(
            name="translation",
            base_url="http://translation:8002",
            health_path="/health",
            timeout=8.0
        ))

        # TTS Service
        self.register_service(ServiceEndpoint(
            name="tts",
            base_url="http://tts:8003",
            health_path="/health",
            timeout=10.0  # TTS kann länger dauern
        ))

    def register_service(self, endpoint: ServiceEndpoint):
        """Registriert neuen Service für Health Monitoring"""
        self.services[endpoint.name] = endpoint
        self.service_status[endpoint.name] = ServiceStatus(name=endpoint.name)

        # Circuit Breaker Configuration per Service
        circuit_config = CircuitBreakerConfig(
            failure_threshold=3,      # ASR/TTS können mal länger dauern
            recovery_timeout=45,      # Weniger aggressiv für ML Services
            success_threshold=2,      # Schneller Recovery
            timeout=endpoint.timeout,
            max_recovery_time=300
        )

        circuit_breaker = CircuitBreakerFactory.get_circuit_breaker(
            endpoint.name, circuit_config
        )
        circuit_breaker.on_state_change = self._on_circuit_state_change
        self.circuit_breakers[endpoint.name] = circuit_breaker

        logger.info(f"📋 Service '{endpoint.name}' registriert: {endpoint.base_url}")

    async def start_monitoring(self):
        """Startet kontinuierliches Health Monitoring"""
        if self.is_monitoring:
            logger.warning("⚠️ Health Monitoring läuft bereits")
            return

        self.is_monitoring = True

        # HTTP Session erstellen
        timeout = aiohttp.ClientTimeout(total=30)
        self.session = aiohttp.ClientSession(timeout=timeout)

        # Health Check Task starten
        self.health_check_task = asyncio.create_task(self._health_check_loop())

        # Initiale Health Checks
        await self._check_all_services()

        logger.info(f"🚀 Service Health Monitoring gestartet (Intervall: {self.check_interval}s)")

    async def stop_monitoring(self):
        """Stoppt Health Monitoring"""
        self.is_monitoring = False

        if self.health_check_task:
            self.health_check_task.cancel()
            try:
                await self.health_check_task
            except asyncio.CancelledError:
                pass
            self.health_check_task = None

        if self.session:
            await self.session.close()
            self.session = None

        logger.info("🛑 Service Health Monitoring gestoppt")

    async def _health_check_loop(self):
        """Kontinuierliche Health Check Loop"""
        try:
            while self.is_monitoring:
                await self._check_all_services()
                await asyncio.sleep(self.check_interval)
        except asyncio.CancelledError:
            logger.info("🔄 Health Check Loop beendet")
            raise
        except Exception as e:
            logger.error(f"❌ Health Check Loop Fehler: {e}")

    async def _check_all_services(self):
        """Überprüft Health Status aller Services"""
        if not self.services:
            return

        # Parallele Health Checks für bessere Performance
        tasks = [
            self._check_service_health(name, endpoint)
            for name, endpoint in self.services.items()
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Log Results
        healthy_count = sum(1 for status in self.service_status.values() if status.is_healthy)
        total_count = len(self.services)

        if healthy_count == total_count:
            logger.debug(f"💚 Alle {total_count} Services sind gesund")
        else:
            unhealthy = [name for name, status in self.service_status.items() if not status.is_healthy]
            logger.warning(f"⚠️ {total_count - healthy_count}/{total_count} Services nicht verfügbar: {unhealthy}")

    async def _check_service_health(self, service_name: str, endpoint: ServiceEndpoint):
        """Health Check für einzelnen Service"""
        status = self.service_status[service_name]
        circuit = self.circuit_breakers[service_name]

        try:
            # Health Check über Circuit Breaker
            health_info = await circuit.call(self._perform_health_request, endpoint)

            # Status Update
            status.is_healthy = True
            status.last_check = datetime.now()
            status.response_time = health_info.get('response_time', 0.0)
            status.error_message = None
            status.status_code = health_info.get('status_code', 200)

            # Extended Health Info wenn verfügbar
            if 'uptime' in health_info:
                status.uptime = health_info['uptime']
            if 'version' in health_info:
                status.version = health_info['version']
            if 'memory_usage' in health_info:
                status.memory_usage = health_info['memory_usage']
            if 'active_connections' in health_info:
                status.active_connections = health_info['active_connections']

        except CircuitBreakerOpenException as e:
            # Circuit ist OPEN - Service als nicht verfügbar markieren
            status.is_healthy = False
            status.last_check = datetime.now()
            status.error_message = str(e)
            status.status_code = None

        except Exception as e:
            # Unerwarteter Fehler
            status.is_healthy = False
            status.last_check = datetime.now()
            status.error_message = str(e)
            status.status_code = getattr(e, 'status', None)

    async def _perform_health_request(self, endpoint: ServiceEndpoint) -> Dict[str, Any]:
        """Führt tatsächlichen Health Check Request aus"""
        start_time = time.time()

        session = self.session
        created_session = False

        if session is None:
            timeout = aiohttp.ClientTimeout(total=max(endpoint.timeout + 5.0, 10.0))
            session = aiohttp.ClientSession(timeout=timeout)
            created_session = True

        try:
            async with session.get(endpoint.health_url) as response:
                response_time = time.time() - start_time

                if response.status == 200:
                    # Try to parse JSON Health Response
                    try:
                        health_data = await response.json()
                        if isinstance(health_data, dict):
                            health_data['response_time'] = response_time
                            health_data['status_code'] = response.status
                            return health_data
                        else:
                            # Not a dict response
                            return {
                                'status': 'healthy',
                                'response_time': response_time,
                                'status_code': response.status,
                                'message': str(health_data)
                            }
                    except (aiohttp.ContentTypeError, ValueError, TypeError):
                        # Non-JSON response - create default response
                        response_text = await response.text()
                        return {
                            'status': 'healthy',
                            'response_time': response_time,
                            'status_code': response.status,
                            'message': response_text[:200] if response_text else 'OK'
                        }
                else:
                    # HTTP Error
                    error_text = await response.text()
                    raise aiohttp.ClientResponseError(
                        request_info=response.request_info,
                        history=response.history,
                        status=response.status,
                        message=f"Health check failed: {error_text[:200]}"
                    )

        except asyncio.TimeoutError:
            response_time = time.time() - start_time
            raise TimeoutError(f"Health check timeout nach {response_time:.2f}s")
        finally:
            if created_session:
                await session.close()

    async def _on_circuit_state_change(self, service_name: str, old_state: CircuitState,
                                     new_state: CircuitState, health_metrics):
        """Callback für Circuit Breaker State Changes"""
        logger.warning(
            f"🔄 Service '{service_name}' Circuit: {old_state.value} → {new_state.value} "
            f"(Success Rate: {health_metrics.success_rate:.1f}%)"
        )

        # Bei kritischen State Changes könnte hier Alerting erfolgen
        if new_state == CircuitState.OPEN:
            await self._handle_service_failure(service_name)
        elif new_state == CircuitState.CLOSED:
            await self._handle_service_recovery(service_name)

    async def _handle_service_failure(self, service_name: str):
        """Behandelt Service Ausfall"""
        logger.error(f"🚨 Service '{service_name}' ist ausgefallen - Graceful Degradation aktiviert")
        # Hier könnte Alerting/Notification Logic stehen

    async def _handle_service_recovery(self, service_name: str):
        """Behandelt Service Recovery"""
        logger.info(f"✅ Service '{service_name}' ist wieder verfügbar")
        # Hier könnte Recovery Notification Logic stehen

    async def call_service(self, service_name: str, func, *args, **kwargs):
        """
        Service Call über Circuit Breaker

        Args:
            service_name: Name des Services
            func: Async Funktion für Service Call
            *args, **kwargs: Parameter für die Funktion

        Returns:
            Service Response oder Exception
        """
        if service_name not in self.circuit_breakers:
            raise ValueError(f"Service '{service_name}' nicht registriert")

        circuit = self.circuit_breakers[service_name]
        return await circuit.call(func, *args, **kwargs)

    def get_service_health(self, service_name: str) -> Optional[Dict[str, Any]]:
        """Health Status für einzelnen Service"""
        if service_name not in self.service_status:
            return None

        status = self.service_status[service_name]
        circuit = self.circuit_breakers[service_name]

        return {
            "service_name": service_name,
            "is_healthy": status.is_healthy,
            "last_check": status.last_check.isoformat() if status.last_check else None,
            "response_time": status.response_time,
            "error_message": status.error_message,
            "status_code": status.status_code,
            "extended_info": {
                "uptime": status.uptime,
                "version": status.version,
                "memory_usage": status.memory_usage,
                "active_connections": status.active_connections
            },
            "circuit_breaker": circuit.get_health_status()
        }

    def get_overall_health(self) -> Dict[str, Any]:
        """Gesamter Health Status aller Services"""
        checked_statuses = {
            name: status for name, status in self.service_status.items()
            if status.last_check is not None
        }

        pending_services = [
            name for name, status in self.service_status.items()
            if status.last_check is None
        ]

        healthy_services = [
            name for name, status in checked_statuses.items() if status.is_healthy
        ]
        unhealthy_services = [
            name for name, status in checked_statuses.items() if not status.is_healthy
        ]

        total_services = len(self.services)
        healthy_count = len(healthy_services)

        overall_healthy = len(unhealthy_services) == 0 and healthy_count > 0

        return {
            "overall_healthy": overall_healthy,
            "summary": {
                "total_services": total_services,
                "healthy_services": healthy_count,
                "unhealthy_services": len(unhealthy_services),
                "success_rate": (healthy_count / total_services * 100) if total_services > 0 else 0
            },
            "services": {
                "healthy": healthy_services,
                "unhealthy": unhealthy_services,
                "pending": pending_services
            },
            "detailed_status": {
                name: self.get_service_health(name)
                for name in self.services.keys()
            },
            "monitoring_info": {
                "is_monitoring": self.is_monitoring,
                "check_interval": self.check_interval,
                "last_check": max(
                    [status.last_check for status in self.service_status.values() if status.last_check],
                    default=None
                )
            }
        }

    def is_service_healthy(self, service_name: str) -> bool:
        """Prüft ob Service gesund ist"""
        if service_name not in self.service_status:
            return False
        return self.service_status[service_name].is_healthy

    def get_healthy_services(self) -> List[str]:
        """Liste aller gesunden Services"""
        return [
            name for name, status in self.service_status.items()
            if status.is_healthy
        ]

    def get_unhealthy_services(self) -> List[str]:
        """Liste aller ungesunden Services"""
        return [
            name for name, status in self.service_status.items()
            if not status.is_healthy
        ]


# Globale Service Health Manager Instanz
service_health_manager = ServiceHealthManager()