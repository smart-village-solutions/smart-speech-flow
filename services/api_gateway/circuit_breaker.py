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
import math
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)

# A transition that has already been applied to the state machine and still
# needs announcing. Carried out of the lock so the callback never runs under it.
Transition = Tuple["CircuitState", "CircuitState"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


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

        # The state machine is driven from the gateway's event loop (health
        # polling) and from pipeline worker threads (#189/#191) at the same
        # time. Every mutation below happens under this lock; the callback
        # never does, so a slow notification cannot stall a transition.
        self._lock = threading.RLock()
        # Where to run the async state-change callback from a worker thread.
        # Bound once the loop exists, which is after this object is built.
        self._notify_loop: Optional[asyncio.AbstractEventLoop] = None

        logger.info(f"🔧 Circuit Breaker '{name}' initialisiert: {self.config}")

    def bind_loop(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Names the loop that state-change callbacks run on.

        Called when health monitoring starts. Without it a transition made on a
        worker thread has nowhere to dispatch its callback and is logged
        instead -- which costs a log line, never the transition itself.
        """
        self._notify_loop = loop or asyncio.get_running_loop()

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
        self._notify_loop = asyncio.get_running_loop()
        await self._announce(self._admit())

        # Request Execution mit Timeout
        start_time = time.time()
        try:
            # Timeout Protection
            timeout = self.config.timeout
            effective_timeout = None
            if timeout is not None:
                slack = max(0.2, timeout * 0.1)
                effective_timeout = timeout + slack

            result = await asyncio.wait_for(func(*args, **kwargs), timeout=effective_timeout)

            # Success Handling
            execution_time = time.time() - start_time
            await self._announce(self._apply_success(execution_time))
            return result

        except asyncio.TimeoutError:
            execution_time = time.time() - start_time
            await self._announce(self._apply_failure(f"Timeout nach {execution_time:.2f}s"))
            raise TimeoutError(f"Service '{self.name}' Timeout nach {execution_time:.2f}s")

        except Exception as e:
            await self._announce(self._apply_failure(str(e)))
            raise

    # --- Synchronous front door ------------------------------------------
    # The pipeline functions are synchronous and run on a worker thread under
    # PipelineAdmission, so they cannot await. These drive the same state
    # machine `call()` drives; a second one would drift from it.

    @contextmanager
    def guard(self) -> Iterator["CircuitBreaker"]:
        """Admits one call, or raises ``CircuitBreakerOpenError`` without running it.

        Records nothing on its own: the caller decides whether the outcome was
        a success or a failure, because an HTTP reply can be both delivered and
        wrong. Pair every ``guard()`` with exactly one ``record_*`` call.
        """
        self._dispatch(self._admit())
        yield self

    def record_success(self, response_time: float) -> None:
        """Counts a completed call and advances the state machine."""
        self._dispatch(self._apply_success(response_time))

    def record_failure(self, error: str) -> None:
        """Counts a failed call and opens the circuit once the threshold is met."""
        self._dispatch(self._apply_failure(error))

    def time_until_next_attempt(self) -> float:
        """Seconds until an open circuit will admit a probe. Zero when closed."""
        with self._lock:
            return self._time_until_next_attempt()

    # --- The state machine itself -----------------------------------------
    # Each returns the transition it made, for the caller to announce once it
    # is no longer holding the lock.

    def _admit(self) -> Optional[Transition]:
        with self._lock:
            if self.state != CircuitState.OPEN:
                return None
            if not self._should_attempt_reset():
                waiting = self._time_until_next_attempt()
                raise CircuitBreakerOpenError(
                    f"Circuit Breaker '{self.name}' ist OPEN. "
                    f"Nächster Versuch in {waiting:.1f}s",
                    service_name=self.name,
                    retry_after_seconds=math.ceil(waiting),
                )
            return self._half_open()

    def _apply_success(self, response_time: float) -> Optional[Transition]:
        with self._lock:
            self.health.total_requests += 1
            self.health.successful_requests += 1
            self.health.last_success = utc_now()

            # Response Time Tracking
            self.response_times.append(response_time)
            if len(self.response_times) > 100:  # Sliding window
                self.response_times.pop(0)

            self.health.average_response_time = sum(self.response_times) / len(self.response_times)

            transition: Optional[Transition] = None
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.config.success_threshold:
                    transition = self._close_circuit()
            elif self.state == CircuitState.CLOSED:
                self.failure_count = 0  # Reset failure count

            logger.debug(
                f"✅ '{self.name}' Success: {response_time:.3f}s "
                f"(Rate: {self.health.success_rate:.1f}%)"
            )
            return transition

    def _apply_failure(self, error: str) -> Optional[Transition]:
        with self._lock:
            self.health.total_requests += 1
            self.health.failed_requests += 1
            self.health.last_failure = utc_now()

            transition: Optional[Transition] = None
            if self.state == CircuitState.CLOSED:
                self.failure_count += 1
                if self.failure_count >= self.config.failure_threshold:
                    transition = self._open_circuit()
            elif self.state == CircuitState.HALF_OPEN:
                # Zurück zu OPEN bei Fehler im Test
                transition = self._open_circuit()

            logger.warning(f"❌ '{self.name}' Failure: {error} (Count: {self.failure_count})")
            return transition

    def _open_circuit(self) -> Transition:
        """Öffnet Circuit Breaker - Service wird blockiert. Caller holds the lock."""
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

        logger.error(
            f"🔴 Circuit Breaker '{self.name}' OPEN - "
            f"Service blockiert für {self.current_recovery_timeout}s"
        )
        return (old_state, self.state)

    def _close_circuit(self) -> Transition:
        """Schließt Circuit Breaker - Normaler Service. Caller holds the lock."""
        old_state = self.state
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.current_recovery_timeout = self.config.recovery_timeout  # Reset backoff
        self.health.current_state = self.state

        logger.info(f"🟢 Circuit Breaker '{self.name}' CLOSED - Service wieder verfügbar")
        return (old_state, self.state)

    def _half_open(self) -> Transition:
        """Versucht Circuit zu schließen (HALF_OPEN State). Caller holds the lock."""
        old_state = self.state
        self.state = CircuitState.HALF_OPEN
        self.success_count = 0
        self.health.current_state = self.state

        logger.info(f"🟡 Circuit Breaker '{self.name}' HALF_OPEN - Teste Service Verfügbarkeit")
        return (old_state, self.state)

    async def _attempt_reset(self):
        """Versucht Circuit zu schließen (HALF_OPEN State)"""
        with self._lock:
            transition = self._half_open()
        await self._announce(transition)

    # --- Announcing a transition ------------------------------------------

    async def _announce(self, transition: Optional[Transition]) -> None:
        """Runs the state-change callback from the loop. Never under the lock."""
        if transition is None:
            return
        await self._notify_state_change(*transition)

    def _dispatch(self, transition: Optional[Transition]) -> None:
        """Announces a transition made off the loop.

        The callback is a coroutine, so it needs a loop to run on. Losing it
        costs a log line and nothing else -- the transition has already been
        applied by the time we get here, so this must never raise.
        """
        if transition is None or self.on_state_change is None:
            return

        old_state, new_state = transition
        loop = self._notify_loop
        if loop is not None and not loop.is_closed():
            try:
                asyncio.run_coroutine_threadsafe(
                    self._notify_state_change(old_state, new_state), loop
                )
                return
            except RuntimeError:
                pass

        logger.warning(
            "🔄 Circuit '%s': %s → %s (no running loop; callback not dispatched)",
            self.name,
            old_state.value,
            new_state.value,
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

    async def _notify_state_change(self, old_state: CircuitState, new_state: CircuitState):
        """Benachrichtigt über State Changes"""
        if self.on_state_change:
            try:
                await self.on_state_change(self.name, old_state, new_state, self.health)
            except Exception:
                logger.exception("State change notification failed")

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
                    self.health.last_failure.isoformat() if self.health.last_failure else None
                ),
                "last_success": (
                    self.health.last_success.isoformat() if self.health.last_success else None
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
    """Raised instead of calling a service whose circuit is open.

    Carries the wait so a caller can answer with a ``Retry-After`` the client
    can act on. Reading it off the breaker afterwards would be a second clock
    read and would disagree with the message by a few milliseconds.
    """

    def __init__(
        self,
        message: str,
        *,
        service_name: str = "",
        retry_after_seconds: int = 1,
    ) -> None:
        super().__init__(message)
        self.service_name = service_name
        # Whole seconds and never below one, so the header and the body agree.
        self.retry_after_seconds = max(1, retry_after_seconds)


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
