"""
Graceful Degradation Manager für Smart Speech Flow Backend
==========================================================

Fallback-Mechanismen bei Service-Ausfällen:
- Cached Response Handling
- Error Message Generation
- Alternative Service Routes
- Service Quality Degradation

Autor: Smart Village Solutions
Datum: November 2025
Version: 1.0
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ServiceMode(Enum):
    """Service Betriebsmodi"""

    FULL = "full"  # Alle Services verfügbar
    DEGRADED = "degraded"  # Eingeschränkte Funktionalität
    MINIMAL = "minimal"  # Nur Basis-Features
    OFFLINE = "offline"  # Kein Service verfügbar


class FallbackStrategy(Enum):
    """Fallback Strategien"""

    CACHED_RESPONSE = "cached_response"  # Gecachte Antworten verwenden
    ERROR_MESSAGE = "error_message"  # Benutzerfreundliche Fehlermeldung
    QUEUE_REQUEST = "queue_request"  # Request für später vormerken


@dataclass
class CacheEntry:
    """Cache Entry für Service Responses"""

    key: str
    data: Any
    timestamp: datetime
    ttl: int = 300  # 5 Minuten Default TTL
    service_name: str = ""

    @property
    def is_valid(self) -> bool:
        """Prüft ob Cache Entry noch gültig ist"""
        return utc_now() < self.timestamp + timedelta(seconds=self.ttl)

    @property
    def age_seconds(self) -> float:
        """Alter des Cache Entries in Sekunden"""
        return (utc_now() - self.timestamp).total_seconds()


@dataclass
class FallbackConfig:
    """Konfiguration für Fallback Verhalten"""

    strategy: FallbackStrategy = FallbackStrategy.CACHED_RESPONSE  # Default Strategy
    cache_ttl: int = 300  # Cache Time-To-Live
    max_cache_size: int = 1000  # Max Cache Entries
    enable_queuing: bool = False  # Request Queuing bei Ausfällen
    queue_timeout: int = 300  # Max Queue Zeit


class GracefulDegradationManager:
    """
    Graceful Degradation für Service-Ausfälle

    Features:
    - Intelligent Caching mit TTL
    - Benutzerfreundliche Error Messages
    - Alternative Service Routing
    - Quality Degradation Patterns
    - Request Queuing für Recovery
    """

    def __init__(self):
        # Cache Management
        self.response_cache: Dict[str, CacheEntry] = {}
        self.cache_stats = {"hits": 0, "misses": 0, "evictions": 0}

        # Service Mode Management
        self.current_mode = ServiceMode.FULL
        self.mode_history: List[Dict] = []

        # Fallback Configuration
        self.fallback_config = FallbackConfig()

        # Request Queue für Recovery
        self.pending_requests: List[Dict] = []

        # Predefined Error Messages
        self._setup_error_messages()

        logger.info("🛡️ Graceful Degradation Manager initialisiert")

    def _setup_error_messages(self):
        """Setup benutzerfreundliche Fehlermeldungen"""
        self.error_messages = {
            "asr": {
                "title": "🎤 Spracherkennung nicht verfügbar",
                "message": "Die Spracherkennung ist vorübergehend nicht verfügbar. Bitte verwenden Sie die Texteingabe.",
                "suggestion": "Geben Sie Ihre Nachricht als Text ein oder versuchen Sie es später erneut.",
                "fallback_action": "text_input",
            },
            "translation": {
                "title": "🌍 Übersetzung eingeschränkt",
                "message": "Der Übersetzungsservice ist eingeschränkt verfügbar.",
                "suggestion": "Grundlegende Übersetzungen sind weiterhin möglich.",
                "fallback_action": "basic_translation",
            },
            "tts": {
                "title": "🔊 Sprachausgabe nicht verfügbar",
                "message": "Die Sprachausgabe ist vorübergehend nicht verfügbar.",
                "suggestion": "Die Übersetzung wird als Text angezeigt.",
                "fallback_action": "text_output",
            },
            "general": {
                "title": "⚠️ Service eingeschränkt verfügbar",
                "message": "Einige Funktionen sind vorübergehend nicht verfügbar.",
                "suggestion": "Basis-Funktionen stehen weiterhin zur Verfügung.",
                "fallback_action": "limited_service",
            },
        }

    async def handle_service_failure(
        self, service_name: str, request_data: Dict, original_error: Exception
    ) -> Dict[str, Any]:
        """
        Behandelt Service-Ausfälle mit Fallback-Strategien

        Args:
            service_name: Name des ausgefallenen Services
            request_data: Original Request Daten
            original_error: Original Exception

        Returns:
            Fallback Response oder Error Message
        """
        logger.warning(f"🚨 Service Failure: {service_name} - Fallback aktiviert")

        # Update Service Mode
        await self._update_service_mode(service_name, is_failure=True)

        # Versuche verschiedene Fallback-Strategien
        # A cached response is a real response this service once produced.
        # Everything else now reports the failure: nothing here may invent a
        # transcript, a translation or audio and present it as a result.
        fallback_strategies = [
            FallbackStrategy.CACHED_RESPONSE,
            FallbackStrategy.ERROR_MESSAGE,
        ]

        for strategy in fallback_strategies:
            try:
                result = self._apply_fallback_strategy(
                    strategy, service_name, request_data, original_error
                )
                if result is not None:
                    return result
            except Exception as e:
                logger.warning(f"⚠️ Fallback Strategy {strategy.value} failed: {e}")
                continue

        # Letzter Fallback: Error Message
        return self._generate_error_response(service_name, original_error)

    def _apply_fallback_strategy(
        self,
        strategy: FallbackStrategy,
        service_name: str,
        request_data: Dict,
        _original_error: Exception,
    ) -> Optional[Dict[str, Any]]:
        """Wendet spezifische Fallback-Strategie an"""

        if strategy == FallbackStrategy.CACHED_RESPONSE:
            return self._try_cached_response(service_name, request_data)

        if strategy == FallbackStrategy.QUEUE_REQUEST:
            return self._queue_request(service_name, request_data)

        return None

    def _try_cached_response(
        self, service_name: str, request_data: Dict
    ) -> Optional[Dict[str, Any]]:
        """Versucht gecachte Response zu verwenden"""
        cache_key = self._generate_cache_key(service_name, request_data)

        if cache_key in self.response_cache:
            cache_entry = self.response_cache[cache_key]

            if cache_entry.is_valid:
                self.cache_stats["hits"] += 1
                logger.info(
                    f"💾 Cache Hit für {service_name}: {cache_key} (Alter: {cache_entry.age_seconds:.1f}s)"
                )

                # Cache Response mit Metadata
                response = cache_entry.data.copy()
                response.update(
                    {
                        "cached": True,
                        "cache_age": cache_entry.age_seconds,
                        "fallback_reason": "service_unavailable",
                        "original_timestamp": cache_entry.timestamp.isoformat(),
                    }
                )
                return response
            else:
                # Expired Cache Entry entfernen
                del self.response_cache[cache_key]

        self.cache_stats["misses"] += 1
        return None

    def _queue_request(self, service_name: str, _request_data: Dict) -> Dict[str, Any] | None:
        """Reiht Request für späteren Retry ein"""
        if not self.fallback_config.enable_queuing:
            return None

        request_id = f"{service_name}_{int(time.time())}_{len(self.pending_requests)}"

        queued_request = {
            "id": request_id,
            "service_name": service_name,
            "request_data": _request_data,
            "timestamp": utc_now(),
            "retry_count": 0,
            "max_retries": 3,
        }

        self.pending_requests.append(queued_request)

        logger.info(f"📋 Request queued: {request_id}")

        return {
            "success": False,
            "queued": True,
            "request_id": request_id,
            "message": "Request wurde vorgemerkt und wird automatisch wiederholt",
            "estimated_retry": "in wenigen Minuten",
        }

    def _generate_error_response(
        self, service_name: str, original_error: Exception
    ) -> Dict[str, Any]:
        """Generiert benutzerfreundliche Fehlermeldung"""
        error_info = self.error_messages.get(service_name, self.error_messages["general"])

        return {
            "success": False,
            "error_type": "service_unavailable",
            "service_name": service_name,
            "title": error_info["title"],
            "message": error_info["message"],
            "suggestion": error_info["suggestion"],
            "fallback_action": error_info["fallback_action"],
            "technical_error": str(original_error),
            "timestamp": utc_now().isoformat(),
            "retry_recommended": True,
            "estimated_recovery": "5-10 Minuten",
        }

    async def cache_response(
        self,
        service_name: str,
        request_data: Dict,
        response_data: Dict,
        ttl: Optional[int] = None,
    ):
        """Cached erfolgreiche Response für Fallback"""
        await asyncio.sleep(0)
        cache_key = self._generate_cache_key(service_name, request_data)
        cache_ttl = ttl or self.fallback_config.cache_ttl

        # Cache Entry erstellen
        cache_entry = CacheEntry(
            key=cache_key,
            data=response_data.copy(),
            timestamp=utc_now(),
            ttl=cache_ttl,
            service_name=service_name,
        )

        # Cache Size Management
        if len(self.response_cache) >= self.fallback_config.max_cache_size:
            self._evict_oldest_cache_entries()

        self.response_cache[cache_key] = cache_entry
        logger.debug(f"💾 Response gecached: {service_name} -> {cache_key} (TTL: {cache_ttl}s)")

    def _generate_cache_key(self, service_name: str, request_data: Dict) -> str:
        """Generiert Cache Key für Request"""
        # Nur relevante Felder für Cache Key verwenden
        relevant_data = {}

        if service_name == "asr":
            # Für ASR: Audio Hash oder Transcription ID
            relevant_data = {
                "audio_hash": request_data.get("audio_hash", ""),
                "language": request_data.get("source_language", ""),
            }
        elif service_name == "translation":
            # Für Translation: Text + Sprach-Kombination
            relevant_data = {
                "text": request_data.get("text", "")[:100],  # Ersten 100 Zeichen
                "source_lang": request_data.get("source_language", ""),
                "target_lang": request_data.get("target_language", ""),
            }
        elif service_name == "tts":
            # Für TTS: Text + Voice Settings
            relevant_data = {
                "text": request_data.get("text", "")[:100],
                "language": request_data.get("language", ""),
                "voice": request_data.get("voice_id", ""),
            }

        # JSON String als Cache Key
        key_data = json.dumps(relevant_data, sort_keys=True)
        return f"{service_name}:{hash(key_data)}"

    def _evict_oldest_cache_entries(self):
        """Entfernt älteste Cache Entries"""
        if not self.response_cache:
            return

        # Sortiere nach Timestamp (älteste zuerst)
        sorted_entries = sorted(self.response_cache.items(), key=lambda x: x[1].timestamp)

        # Entferne älteste 10% der Entries
        evict_count = max(1, len(sorted_entries) // 10)

        for i in range(evict_count):
            key, _ = sorted_entries[i]
            del self.response_cache[key]
            self.cache_stats["evictions"] += 1

        logger.debug(f"🗑️ {evict_count} Cache Entries entfernt")

    def apply_service_states(self, usable: Dict[str, bool]) -> None:
        """Recomputes the reported mode from which services are callable.

        Derived rather than accumulated. ``_update_service_mode`` only ever
        made the mode worse -- its recovery branch was a literal ``pass`` -- so
        a single failure pinned the endpoint to DEGRADED for the life of the
        process. Recomputing means recovery needs no separate path and cannot
        be forgotten.

        ``usable`` maps each service to whether its breaker will currently
        admit a request; HALF_OPEN counts as usable, because it will.
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

    def _record_mode(self, new_mode: "ServiceMode", *, trigger: str) -> None:
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

    async def _update_service_mode(self, service_name: str, is_failure: bool):
        """Updated Service Betriebsmodus"""
        await asyncio.sleep(0)
        old_mode = self.current_mode

        if is_failure:
            # Service Mode verschlechtern
            if self.current_mode == ServiceMode.FULL:
                self.current_mode = ServiceMode.DEGRADED
            elif self.current_mode == ServiceMode.DEGRADED:
                self.current_mode = ServiceMode.MINIMAL
        else:
            # Service Mode verbessern (bei Recovery)
            # Dies würde bei Service Recovery aufgerufen
            pass

        if old_mode != self.current_mode:
            self.mode_history.append(
                {
                    "timestamp": utc_now().isoformat(),
                    "old_mode": old_mode.value,
                    "new_mode": self.current_mode.value,
                    "trigger_service": service_name,
                    "is_failure": is_failure,
                }
            )

            logger.warning(
                f"🔄 Service Mode: {old_mode.value} → {self.current_mode.value} (Trigger: {service_name})"
            )

    async def process_pending_requests(self):
        """Verarbeitet wartende Requests nach Service Recovery"""
        await asyncio.sleep(0)
        if not self.pending_requests:
            return

        current_time = utc_now()
        processed_requests = []

        for request in self.pending_requests:
            # Timeout Check
            age = (current_time - request["timestamp"]).seconds
            if age > self.fallback_config.queue_timeout:
                logger.warning(f"⏰ Queued Request {request['id']} timed out")
                processed_requests.append(request)
                continue

            # Retry Logic hier implementieren
            logger.info(f"🔄 Retry queued request: {request['id']}")
            processed_requests.append(request)

        # Processed Requests entfernen
        for request in processed_requests:
            if request in self.pending_requests:
                self.pending_requests.remove(request)

    def get_degradation_status(self) -> Dict[str, Any]:
        """Aktueller Degradation Status"""
        return {
            "current_mode": self.current_mode.value,
            "cache_stats": self.cache_stats.copy(),
            "cache_size": len(self.response_cache),
            "pending_requests": len(self.pending_requests),
            "mode_history": self.mode_history[-10:],  # Letzte 10 Mode Changes
            "fallback_config": {
                "cache_ttl": self.fallback_config.cache_ttl,
                "max_cache_size": self.fallback_config.max_cache_size,
                "enable_queuing": self.fallback_config.enable_queuing,
            },
        }

    async def cleanup_expired_cache(self):
        """Entfernt abgelaufene Cache Entries"""
        await asyncio.sleep(0)
        expired_keys = [key for key, entry in self.response_cache.items() if not entry.is_valid]

        for key in expired_keys:
            del self.response_cache[key]

        if expired_keys:
            logger.debug(f"🧹 {len(expired_keys)} abgelaufene Cache Entries entfernt")


# Globale Degradation Manager Instanz
graceful_degradation_manager = GracefulDegradationManager()
