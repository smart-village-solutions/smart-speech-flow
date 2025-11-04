"""
Circuit Breaker Pattern Implementation für Smart Speech Flow Backend
==================================================================

Circuit Breaker verhindert kaskadische Ausfälle und bietet graceful degradation
bei Service-Problemen. Implementiert die klassischen States:
- CLOSED: Normaler Betrieb
- OPEN: Service blockiert nach Failure-Threshold
- HALF_OPEN: Test ob Service wieder verfügbar ist

Autor: Smart Village Solutions
Datum: November 2025
Version: 1.0
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit Breaker States"""

    CLOSED = "closed"  # Service funktioniert normal
    OPEN = "open"  # Service blockiert nach Fehlern
    HALF_OPEN = "half_open"  # Test ob Service wieder verfügbar


@dataclass
class CircuitBreakerConfig:
    """Konfiguration für Circuit Breaker"""

    failure_threshold: int = 5  # Anzahl Fehler bis OPEN
    recovery_timeout: int = 60  # Sekunden bis HALF_OPEN Test
    success_threshold: int = 3  # Erfolge für CLOSED Status
    timeout: float = 10.0  # Request Timeout in Sekunden

    # Exponential Backoff für Recovery
    max_recovery_time: int = 300  # Max 5 Minuten
    backoff_multiplier: float = 2.0  # Verdopplung der Wartezeit


@dataclass
class ServiceHealth:
    """Service Health Metrics"""

    service_name: str
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    last_failure: Optional[datetime] = None
    last_success: Optional[datetime] = None
    average_response_time: float = 0.0
    current_state: CircuitState = CircuitState.CLOSED

    @property
    def success_rate(self) -> float:
        """Erfolgsrate in Prozent"""
        if self.total_requests == 0:
            return 100.0
        return (self.successful_requests / self.total_requests) * 100.0

    @property
    def failure_rate(self) -> float:
        """Fehlerrate in Prozent"""
        return 100.0 - self.success_rate


class CircuitBreaker:
    """
    Circuit Breaker Implementation für Service Health Management

    Verhindert kaskadische Ausfälle durch:
    - Failure Tracking und Threshold Management
    - Automatic Service Blocking bei kritischen Fehlern
    - Smart Recovery mit exponential backoff
    - Detailed Health Metrics und Monitoring
    """

    def __init__(self, name: str, config: CircuitBreakerConfig = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()

        # Circuit State Management
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0

        # Timing Management
        self.last_failure_time = None
        self.next_attempt_time = None
        self.current_recovery_timeout = self.config.recovery_timeout

        # Health Metrics
        self.health = ServiceHealth(service_name=name)
        self.response_times: List[float] = []

        # Callbacks
        self.on_state_change: Optional[Callable] = None

        logger.info(f"🔧 Circuit Breaker '{name}' initialisiert: {self.config}")

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Führt Funktion mit Circuit Breaker Protection aus

        Args:
            func: Async Funktion die aufgerufen werden soll
            *args, **kwargs: Parameter für die Funktion

        Returns:
            Ergebnis der Funktion oder Exception

        Raises:
            CircuitBreakerOpenError: Wenn Circuit OPEN ist
            TimeoutError: Bei Timeout
        """
        # Circuit State Check
        if self.state == CircuitState.OPEN:
            if self._should_attempt_reset():
                await self._attempt_reset()
            else:
                raise CircuitBreakerOpenError(
                    f"Circuit Breaker '{self.name}' ist OPEN. "
                    f"Nächster Versuch in {self._time_until_next_attempt():.1f}s"
                )

        # Request Execution mit Timeout
        start_time = time.time()
        try:
            # Timeout Protection
            timeout = self.config.timeout
            effective_timeout = None
            if timeout is not None:
                slack = max(0.2, timeout * 0.1)
                effective_timeout = timeout + slack

            result = await asyncio.wait_for(
                func(*args, **kwargs), timeout=effective_timeout
            )

            # Success Handling
            execution_time = time.time() - start_time
            await self._on_success(execution_time)
            return result

        except asyncio.TimeoutError:
            execution_time = time.time() - start_time
            await self._on_failure(f"Timeout nach {execution_time:.2f}s")
            raise TimeoutError(
                f"Service '{self.name}' Timeout nach {execution_time:.2f}s"
            )

        except Exception as e:
            execution_time = time.time() - start_time
            await self._on_failure(str(e))
            raise

    async def _on_success(self, response_time: float):
        """Behandelt erfolgreiche Requests"""
        self.health.total_requests += 1
        self.health.successful_requests += 1
        self.health.last_success = datetime.now()

        # Response Time Tracking
        self.response_times.append(response_time)
        if len(self.response_times) > 100:  # Sliding window
            self.response_times.pop(0)

        self.health.average_response_time = sum(self.response_times) / len(
            self.response_times
        )

        # State Management
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.config.success_threshold:
                await self._close_circuit()
        elif self.state == CircuitState.CLOSED:
            self.failure_count = 0  # Reset failure count

        logger.debug(
            f"✅ '{self.name}' Success: {response_time:.3f}s (Rate: {self.health.success_rate:.1f}%)"
        )

    async def _on_failure(self, error: str):
        """Behandelt fehlgeschlagene Requests"""
        self.health.total_requests += 1
        self.health.failed_requests += 1
        self.health.last_failure = datetime.now()

        # State Management
        if self.state == CircuitState.CLOSED:
            self.failure_count += 1
            if self.failure_count >= self.config.failure_threshold:
                await self._open_circuit()
        elif self.state == CircuitState.HALF_OPEN:
            # Zurück zu OPEN bei Fehler im Test
            await self._open_circuit()

        logger.warning(
            f"❌ '{self.name}' Failure: {error} (Count: {self.failure_count})"
        )

    async def _open_circuit(self):
        """Öffnet Circuit Breaker - Service wird blockiert"""
        old_state = self.state
        self.state = CircuitState.OPEN
        self.last_failure_time = time.time()

        # Exponential Backoff für Recovery Time
        if old_state == CircuitState.HALF_OPEN:
            self.current_recovery_timeout = min(
                self.current_recovery_timeout * self.config.backoff_multiplier,
                self.config.max_recovery_time,
            )

        self.next_attempt_time = self.last_failure_time + self.current_recovery_timeout
        self.health.current_state = self.state

        await self._notify_state_change(old_state, self.state)
        logger.error(
            f"🔴 Circuit Breaker '{self.name}' OPEN - Service blockiert für {self.current_recovery_timeout}s"
        )

    async def _close_circuit(self):
        """Schließt Circuit Breaker - Normaler Service"""
        old_state = self.state
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.current_recovery_timeout = self.config.recovery_timeout  # Reset backoff
        self.health.current_state = self.state

        await self._notify_state_change(old_state, self.state)
        logger.info(
            f"🟢 Circuit Breaker '{self.name}' CLOSED - Service wieder verfügbar"
        )

    async def _attempt_reset(self):
        """Versucht Circuit zu schließen (HALF_OPEN State)"""
        old_state = self.state
        self.state = CircuitState.HALF_OPEN
        self.success_count = 0
        self.health.current_state = self.state

        await self._notify_state_change(old_state, self.state)
        logger.info(
            f"🟡 Circuit Breaker '{self.name}' HALF_OPEN - Teste Service Verfügbarkeit"
        )

    def _should_attempt_reset(self) -> bool:
        """Prüft ob Reset-Versuch erlaubt ist"""
        if self.next_attempt_time is None:
            return True
        return time.time() >= self.next_attempt_time

    def _time_until_next_attempt(self) -> float:
        """Zeit bis zum nächsten Reset-Versuch"""
        if self.next_attempt_time is None:
            return 0.0
        return max(0.0, self.next_attempt_time - time.time())

    async def _notify_state_change(
        self, old_state: CircuitState, new_state: CircuitState
    ):
        """Benachrichtigt über State Changes"""
        if self.on_state_change:
            try:
                await self.on_state_change(self.name, old_state, new_state, self.health)
            except Exception as e:
                logger.error(f"❌ State Change Notification Fehler: {e}")

    def get_health_status(self) -> Dict[str, Any]:
        """Aktueller Health Status"""
        return {
            "service_name": self.name,
            "state": self.state.value,
            "health_metrics": {
                "total_requests": self.health.total_requests,
                "successful_requests": self.health.successful_requests,
                "failed_requests": self.health.failed_requests,
                "success_rate": round(self.health.success_rate, 2),
                "failure_rate": round(self.health.failure_rate, 2),
                "average_response_time": round(self.health.average_response_time, 3),
            },
            "circuit_info": {
                "failure_count": self.failure_count,
                "success_count": self.success_count,
                "time_until_next_attempt": round(self._time_until_next_attempt(), 1),
                "current_recovery_timeout": self.current_recovery_timeout,
            },
            "last_events": {
                "last_failure": (
                    self.health.last_failure.isoformat()
                    if self.health.last_failure
                    else None
                ),
                "last_success": (
                    self.health.last_success.isoformat()
                    if self.health.last_success
                    else None
                ),
            },
        }

    def reset(self):
        """Manueller Circuit Reset - nur für Admin/Testing"""
        logger.warning(f"⚠️ Manueller Reset von Circuit Breaker '{self.name}'")
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        self.next_attempt_time = None
        self.current_recovery_timeout = self.config.recovery_timeout
        self.health.current_state = self.state


class CircuitBreakerOpenError(Exception):
    """Exception wenn Circuit Breaker OPEN ist"""

    pass


# Factory für Circuit Breaker Instanzen
class CircuitBreakerFactory:
    """Factory für Service-spezifische Circuit Breaker"""

    _instances: Dict[str, CircuitBreaker] = {}

    @classmethod
    def get_circuit_breaker(
        cls, service_name: str, config: CircuitBreakerConfig = None
    ) -> CircuitBreaker:
        """Holt oder erstellt Circuit Breaker für Service"""
        if service_name not in cls._instances:
            cls._instances[service_name] = CircuitBreaker(service_name, config)
        return cls._instances[service_name]

    @classmethod
    def get_all_circuits(cls) -> Dict[str, CircuitBreaker]:
        """Alle Circuit Breaker Instanzen"""
        return cls._instances.copy()

    @classmethod
    def reset_all(cls):
        """Reset aller Circuit Breaker - nur für Testing"""
        for circuit in cls._instances.values():
            circuit.reset()
        logger.warning("⚠️ Alle Circuit Breaker wurden zurückgesetzt")
