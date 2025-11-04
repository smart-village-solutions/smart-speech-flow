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

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


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
    ALTERNATIVE_SERVICE = "alternative"  # Alternativen Service nutzen
    DEGRADED_QUALITY = "degraded_quality"  # Reduzierte Qualität
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
        return datetime.now() < self.timestamp + timedelta(seconds=self.ttl)

    @property
    def age_seconds(self) -> float:
        """Alter des Cache Entries in Sekunden"""
        return (datetime.now() - self.timestamp).total_seconds()


@dataclass
class FallbackConfig:
    """Konfiguration für Fallback Verhalten"""

    strategy: FallbackStrategy = FallbackStrategy.CACHED_RESPONSE  # Default Strategy
    cache_ttl: int = 300  # Cache Time-To-Live
    max_cache_size: int = 1000  # Max Cache Entries
    enable_queuing: bool = False  # Request Queuing bei Ausfällen
    queue_timeout: int = 300  # Max Queue Zeit

    # Service-spezifische Fallbacks
    alternative_services: Dict[str, List[str]] = field(default_factory=dict)

    # Quality Degradation Settings
    degraded_quality_factor: float = 0.7  # 70% Qualität bei Degradation


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

        # Alternative Service Mappings
        self._setup_service_alternatives()

        # Predefined Error Messages
        self._setup_error_messages()

        logger.info("🛡️ Graceful Degradation Manager initialisiert")

    def _setup_service_alternatives(self):
        """Setup Alternative Service Mappings"""
        # Beispiel: Falls ASR ausfällt, könnte ein einfacherer Service verwendet werden
        self.fallback_config.alternative_services = {
            "asr": ["asr-backup", "asr-simple"],  # Backup ASR Services
            "translation": ["translation-basic"],  # Basis-Übersetzung
            "tts": ["tts-simple"],  # Einfache TTS
        }

        logger.debug("🔀 Service Alternativen konfiguriert")

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
        fallback_strategies = [
            FallbackStrategy.CACHED_RESPONSE,
            FallbackStrategy.ALTERNATIVE_SERVICE,
            FallbackStrategy.DEGRADED_QUALITY,
            FallbackStrategy.ERROR_MESSAGE,
        ]

        for strategy in fallback_strategies:
            try:
                result = await self._apply_fallback_strategy(
                    strategy, service_name, request_data, original_error
                )
                if result is not None:
                    return result
            except Exception as e:
                logger.warning(f"⚠️ Fallback Strategy {strategy.value} failed: {e}")
                continue

        # Letzter Fallback: Error Message
        return await self._generate_error_response(service_name, original_error)

    async def _apply_fallback_strategy(
        self,
        strategy: FallbackStrategy,
        service_name: str,
        request_data: Dict,
        original_error: Exception,
    ) -> Optional[Dict[str, Any]]:
        """Wendet spezifische Fallback-Strategie an"""

        if strategy == FallbackStrategy.CACHED_RESPONSE:
            return await self._try_cached_response(service_name, request_data)

        elif strategy == FallbackStrategy.ALTERNATIVE_SERVICE:
            return await self._try_alternative_service(service_name, request_data)

        elif strategy == FallbackStrategy.DEGRADED_QUALITY:
            return await self._try_degraded_quality(service_name, request_data)

        elif strategy == FallbackStrategy.QUEUE_REQUEST:
            return await self._queue_request(service_name, request_data)

        return None

    async def _try_cached_response(
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

    async def _try_alternative_service(
        self, service_name: str, request_data: Dict
    ) -> Optional[Dict[str, Any]]:
        """Versucht alternativen Service zu verwenden"""
        alternatives = self.fallback_config.alternative_services.get(service_name, [])

        if not alternatives:
            return None

        for alt_service in alternatives:
            try:
                # Hier würde normalerweise der alternative Service aufgerufen
                logger.info(f"🔄 Versuche alternativen Service: {alt_service}")

                # Placeholder für Alternative Service Call
                # result = await self._call_alternative_service(alt_service, request_data)

                # Simulierte Alternative Response
                return {
                    "success": True,
                    "message": f"Processed by alternative service: {alt_service}",
                    "quality": "reduced",
                    "fallback_service": alt_service,
                    "original_service": service_name,
                }

            except Exception as e:
                logger.warning(f"⚠️ Alternative Service {alt_service} failed: {e}")
                continue

        return None

    async def _try_degraded_quality(
        self, service_name: str, request_data: Dict
    ) -> Optional[Dict[str, Any]]:
        """Versucht Service mit reduzierter Qualität"""

        # Service-spezifische Degradation
        if service_name == "asr":
            # Einfachere ASR mit weniger Genauigkeit
            return {
                "success": True,
                "text": "Vereinfachte Spracherkennung aktiv",
                "confidence": 0.6,  # Reduzierte Confidence
                "quality": "degraded",
                "fallback_reason": "service_degradation",
            }

        elif service_name == "translation":
            # Basis-Übersetzung ohne Kontext
            source_text = request_data.get("text", "")
            return {
                "success": True,
                "translated_text": f"[Basis-Übersetzung]: {source_text}",
                "quality": "basic",
                "confidence": 0.5,
                "fallback_reason": "service_degradation",
            }

        elif service_name == "tts":
            # Text-only Output statt Audio
            text = request_data.get("text", "")
            return {
                "success": True,
                "audio_data": None,  # Kein Audio verfügbar
                "text_output": text,
                "fallback_mode": "text_only",
                "fallback_reason": "tts_unavailable",
            }

        return None

    async def _queue_request(
        self, service_name: str, request_data: Dict
    ) -> Dict[str, Any]:
        """Reiht Request für späteren Retry ein"""
        if not self.fallback_config.enable_queuing:
            return None

        request_id = f"{service_name}_{int(time.time())}_{len(self.pending_requests)}"

        queued_request = {
            "id": request_id,
            "service_name": service_name,
            "request_data": request_data,
            "timestamp": datetime.now(),
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

    async def _generate_error_response(
        self, service_name: str, original_error: Exception
    ) -> Dict[str, Any]:
        """Generiert benutzerfreundliche Fehlermeldung"""
        error_info = self.error_messages.get(
            service_name, self.error_messages["general"]
        )

        return {
            "success": False,
            "error_type": "service_unavailable",
            "service_name": service_name,
            "title": error_info["title"],
            "message": error_info["message"],
            "suggestion": error_info["suggestion"],
            "fallback_action": error_info["fallback_action"],
            "technical_error": str(original_error),
            "timestamp": datetime.now().isoformat(),
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
        cache_key = self._generate_cache_key(service_name, request_data)
        cache_ttl = ttl or self.fallback_config.cache_ttl

        # Cache Entry erstellen
        cache_entry = CacheEntry(
            key=cache_key,
            data=response_data.copy(),
            timestamp=datetime.now(),
            ttl=cache_ttl,
            service_name=service_name,
        )

        # Cache Size Management
        if len(self.response_cache) >= self.fallback_config.max_cache_size:
            await self._evict_oldest_cache_entries()

        self.response_cache[cache_key] = cache_entry
        logger.debug(
            f"💾 Response gecached: {service_name} -> {cache_key} (TTL: {cache_ttl}s)"
        )

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

    async def _evict_oldest_cache_entries(self):
        """Entfernt älteste Cache Entries"""
        if not self.response_cache:
            return

        # Sortiere nach Timestamp (älteste zuerst)
        sorted_entries = sorted(
            self.response_cache.items(), key=lambda x: x[1].timestamp
        )

        # Entferne älteste 10% der Entries
        evict_count = max(1, len(sorted_entries) // 10)

        for i in range(evict_count):
            key, _ = sorted_entries[i]
            del self.response_cache[key]
            self.cache_stats["evictions"] += 1

        logger.debug(f"🗑️ {evict_count} Cache Entries entfernt")

    async def _update_service_mode(self, service_name: str, is_failure: bool):
        """Updated Service Betriebsmodus"""
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
                    "timestamp": datetime.now().isoformat(),
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
        if not self.pending_requests:
            return

        current_time = datetime.now()
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
        expired_keys = [
            key for key, entry in self.response_cache.items() if not entry.is_valid
        ]

        for key in expired_keys:
            del self.response_cache[key]

        if expired_keys:
            logger.debug(f"🧹 {len(expired_keys)} abgelaufene Cache Entries entfernt")


# Globale Degradation Manager Instanz
graceful_degradation_manager = GracefulDegradationManager()
