"""
Circuit Breaker Service Integration für Smart Speech Flow Backend
================================================================

Async Wrapper für Service-Calls mit Circuit Breaker Pattern:
- ASR Service Integration
- Translation Service Integration
- TTS Service Integration
- Graceful Degradation Support

Autor: Smart Village Solutions
Datum: November 2025
Version: 1.0
"""

import logging
from typing import Any, Dict, Optional

import aiohttp

from .circuit_breaker import CircuitBreakerOpenError
from .graceful_degradation import graceful_degradation_manager
from .service_health import service_health_manager

logger = logging.getLogger(__name__)


class CircuitBreakerServiceClient:
    """
    Service Client mit Circuit Breaker Integration

    Bietet async Wrapper für alle Smart Speech Flow Services:
    - Automatic Circuit Breaking bei Fehlern
    - Graceful Degradation bei Ausfällen
    - Response Caching für Fallbacks
    - Health Monitoring Integration
    """

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self._session_created = False

    async def _ensure_session(self):
        """Stellt sicher dass HTTP Session verfügbar ist"""
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
            self._session_created = True

    async def close(self):
        """Schließt HTTP Session"""
        if self.session and not self.session.closed:
            await self.session.close()

    async def call_asr_service(
        self, audio_data: bytes, source_lang: str = "de", debug: bool = False
    ) -> Dict[str, Any]:
        """
        ASR Service Call mit Circuit Breaker

        Args:
            audio_data: WAV Audio Bytes
            source_lang: Quellsprache
            debug: Debug Modus

        Returns:
            ASR Response oder Fallback
        """
        await self._ensure_session()

        request_data = {
            "source_language": source_lang,
            "debug": debug,
            "audio_hash": hash(audio_data[:1000]),  # Hash für Caching
        }

        try:
            # Service Call über Circuit Breaker
            result = await service_health_manager.call_service(
                "asr", self._perform_asr_request, audio_data, source_lang, debug
            )

            # Cache erfolgreiche Response
            await graceful_degradation_manager.cache_response(
                "asr", request_data, result, ttl=600  # 10 Min Cache für ASR
            )

            return result

        except CircuitBreakerOpenError as e:
            logger.warning(f"🔴 ASR Circuit Breaker OPEN: {e}")
            return await graceful_degradation_manager.handle_service_failure(
                "asr", request_data, e
            )

        except Exception as e:
            logger.error(f"❌ ASR Service Error: {e}")
            return await graceful_degradation_manager.handle_service_failure(
                "asr", request_data, e
            )

    async def _perform_asr_request(
        self, audio_data: bytes, source_lang: str, debug: bool
    ) -> Dict[str, Any]:
        """Führt tatsächlichen ASR Request aus"""
        url = "http://asr:8000/transcribe"

        # Multipart Form Data für Audio Upload
        form_data = aiohttp.FormData()
        form_data.add_field(
            "file", audio_data, filename="input.wav", content_type="audio/wav"
        )
        form_data.add_field("lang", source_lang)
        form_data.add_field("debug", str(debug).lower())

        async with self.session.post(url, data=form_data) as response:
            if response.status == 200:
                result = await response.json()
                return {
                    "success": True,
                    "text": result.get("text", ""),
                    "confidence": result.get("confidence", 0.0),
                    "processing_time": result.get("processing_time", 0.0),
                    "service": "asr",
                }
            else:
                error_text = await response.text()
                raise aiohttp.ClientResponseError(
                    request_info=response.request_info,
                    history=response.history,
                    status=response.status,
                    message=f"ASR failed: {error_text[:200]}",
                )

    async def call_translation_service(
        self, text: str, source_lang: str, target_lang: str, debug: bool = False
    ) -> Dict[str, Any]:
        """
        Translation Service Call mit Circuit Breaker

        Args:
            text: Zu übersetzender Text
            source_lang: Quellsprache
            target_lang: Zielsprache
            debug: Debug Modus

        Returns:
            Translation Response oder Fallback
        """
        await self._ensure_session()

        request_data = {
            "text": text,
            "source_language": source_lang,
            "target_language": target_lang,
            "debug": debug,
        }

        try:
            # Service Call über Circuit Breaker
            result = await service_health_manager.call_service(
                "translation",
                self._perform_translation_request,
                text,
                source_lang,
                target_lang,
                debug,
            )

            # Cache erfolgreiche Response
            await graceful_degradation_manager.cache_response(
                "translation",
                request_data,
                result,
                ttl=1800,  # 30 Min Cache für Translation
            )

            return result

        except CircuitBreakerOpenError as e:
            logger.warning(f"🔴 Translation Circuit Breaker OPEN: {e}")
            return await graceful_degradation_manager.handle_service_failure(
                "translation", request_data, e
            )

        except Exception as e:
            logger.error(f"❌ Translation Service Error: {e}")
            return await graceful_degradation_manager.handle_service_failure(
                "translation", request_data, e
            )

    async def _perform_translation_request(
        self, text: str, source_lang: str, target_lang: str, debug: bool
    ) -> Dict[str, Any]:
        """Führt tatsächlichen Translation Request aus"""
        url = "http://translation:8000/translate"

        payload = {
            "text": text,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "debug": debug,
        }

        async with self.session.post(url, json=payload) as response:
            if response.status == 200:
                result = await response.json()
                return {
                    "success": True,
                    "translated_text": result.get("translated_text", ""),
                    "confidence": result.get("confidence", 0.0),
                    "processing_time": result.get("processing_time", 0.0),
                    "service": "translation",
                }
            else:
                error_text = await response.text()
                raise aiohttp.ClientResponseError(
                    request_info=response.request_info,
                    history=response.history,
                    status=response.status,
                    message=f"Translation failed: {error_text[:200]}",
                )

    async def call_tts_service(
        self,
        text: str,
        target_lang: str,
        voice_id: str = "default",
        debug: bool = False,
    ) -> Dict[str, Any]:
        """
        TTS Service Call mit Circuit Breaker

        Args:
            text: Zu synthetisierender Text
            target_lang: Zielsprache
            voice_id: Voice ID
            debug: Debug Modus

        Returns:
            TTS Response oder Fallback
        """
        await self._ensure_session()

        request_data = {
            "text": text,
            "language": target_lang,
            "voice_id": voice_id,
            "debug": debug,
        }

        try:
            # Service Call über Circuit Breaker
            result = await service_health_manager.call_service(
                "tts", self._perform_tts_request, text, target_lang, voice_id, debug
            )

            # Cache erfolgreiche Response
            await graceful_degradation_manager.cache_response(
                "tts", request_data, result, ttl=3600  # 1h Cache für TTS
            )

            return result

        except CircuitBreakerOpenError as e:
            logger.warning(f"🔴 TTS Circuit Breaker OPEN: {e}")
            return await graceful_degradation_manager.handle_service_failure(
                "tts", request_data, e
            )

        except Exception as e:
            logger.error(f"❌ TTS Service Error: {e}")
            return await graceful_degradation_manager.handle_service_failure(
                "tts", request_data, e
            )

    async def _perform_tts_request(
        self, text: str, target_lang: str, voice_id: str, debug: bool
    ) -> Dict[str, Any]:
        """Führt tatsächlichen TTS Request aus"""
        url = "http://tts:8000/synthesize"

        payload = {
            "text": text,
            "lang": target_lang,
            "voice_id": voice_id,
            "debug": debug,
        }

        async with self.session.post(url, json=payload) as response:
            if response.status == 200:
                # TTS kann Audio Bytes oder JSON zurückgeben
                content_type = response.headers.get("content-type", "")

                if "audio" in content_type:
                    # Audio Response
                    audio_data = await response.read()
                    return {
                        "success": True,
                        "audio_data": audio_data,
                        "content_type": content_type,
                        "service": "tts",
                    }
                else:
                    # JSON Response
                    result = await response.json()
                    return {
                        "success": True,
                        "audio_url": result.get("audio_url", ""),
                        "processing_time": result.get("processing_time", 0.0),
                        "service": "tts",
                    }
            else:
                error_text = await response.text()
                raise aiohttp.ClientResponseError(
                    request_info=response.request_info,
                    history=response.history,
                    status=response.status,
                    message=f"TTS failed: {error_text[:200]}",
                )

    async def get_health_status(self) -> Dict[str, Any]:
        """Gesamter Health Status aller Services"""
        return service_health_manager.get_overall_health()

    async def get_service_status(self, service_name: str) -> Dict[str, Any]:
        """Health Status für einzelnen Service"""
        return service_health_manager.get_service_health(service_name)

    async def get_degradation_status(self) -> Dict[str, Any]:
        """Aktueller Degradation Status"""
        return graceful_degradation_manager.get_degradation_status()

    async def start_health_monitoring(self):
        """Startet Health Monitoring"""
        await service_health_manager.start_monitoring()
        logger.info("🚀 Circuit Breaker Health Monitoring gestartet")

    async def stop_health_monitoring(self):
        """Stoppt Health Monitoring"""
        await service_health_manager.stop_monitoring()
        await self.close()
        logger.info("🛑 Circuit Breaker Health Monitoring gestoppt")


# Globale Circuit Breaker Service Client Instanz
circuit_breaker_client = CircuitBreakerServiceClient()
