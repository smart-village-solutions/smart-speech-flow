"""The ASR, translation and TTS services behind one port (#228).

The pipeline asks for a transcript, a translation or speech and classifies the
reply itself. `HttpSpeechServices` turns each request into the POST it has
always been, through that service's circuit breaker, and returns the reply
untouched. The transport stays `requests`: see ai_service_client.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Mapping, Protocol

import requests

from .ai_service_client import call_ai_service
from .circuit_breaker import CircuitBreaker

AUDIO_WAV_MIME = "audio/wav"

DOCKER_ENV = os.environ.get("DOCKER_COMPOSE", "1") == "1"
DEFAULT_INTERNAL_SCHEME = os.environ.get("SERVICE_SCHEME", "http")
DEFAULT_LOCAL_SCHEME = os.environ.get("LOCAL_SERVICE_SCHEME", DEFAULT_INTERNAL_SCHEME)


def _build_service_url(host: str, port: int, path: str, *, scheme: str) -> str:
    return f"{scheme}://{host}:{port}{path}"


if DOCKER_ENV:
    ASR_URL = _build_service_url("asr", 8000, "/transcribe", scheme=DEFAULT_INTERNAL_SCHEME)
    TRANSLATION_URL = _build_service_url(
        "translation", 8000, "/translate", scheme=DEFAULT_INTERNAL_SCHEME
    )
    TTS_URL = _build_service_url("tts", 8000, "/synthesize", scheme=DEFAULT_INTERNAL_SCHEME)
else:
    ASR_URL = _build_service_url("localhost", 8001, "/transcribe", scheme=DEFAULT_LOCAL_SCHEME)
    TRANSLATION_URL = _build_service_url(
        "localhost", 8002, "/translate", scheme=DEFAULT_LOCAL_SCHEME
    )
    TTS_URL = _build_service_url("localhost", 8003, "/synthesize", scheme=DEFAULT_LOCAL_SCHEME)


def _tts_served_audio(response: Any) -> bool:
    """Whether a TTS reply actually carried audio.

    TTS answers 200 with a JSON error body when synthesis fails, which
    _finish_tts_stage has always treated as a failure. The breaker needs the
    same view, or it stays CLOSED while every synthesis fails.
    """
    return bool(response.headers.get("content-type", "") == AUDIO_WAV_MIME)


class SpeechServices(Protocol):
    """What the pipeline needs from the speech services."""

    def transcribe(self, audio: bytes, *, lang: str, debug: bool) -> requests.Response: ...

    def translate(self, payload: Dict[str, Any]) -> requests.Response: ...

    def synthesize(self, payload: Dict[str, Any], *, timeout: float) -> requests.Response: ...


class HttpSpeechServices:
    """The speech services over HTTP, each through its own breaker.

    The breakers are the ones the health manager registered and the status
    routes report on. A missing one fails construction: a service the pipeline
    calls without a breaker would be a service no route could report.
    """

    def __init__(
        self,
        breakers: Mapping[str, CircuitBreaker],
        *,
        asr_url: str = ASR_URL,
        translation_url: str = TRANSLATION_URL,
        tts_url: str = TTS_URL,
    ) -> None:
        self._asr = breakers["asr"]
        self._translation = breakers["translation"]
        self._tts = breakers["tts"]
        self._asr_url = asr_url
        self._translation_url = translation_url
        self._tts_url = tts_url

    def transcribe(self, audio: bytes, *, lang: str, debug: bool) -> requests.Response:
        return call_ai_service(
            self._asr,
            self._asr_url,
            files={"file": ("input.wav", audio, AUDIO_WAV_MIME)},
            data={"lang": lang, "debug": str(debug).lower()},
            timeout=60,  # ASR kann länger dauern
        )

    def translate(self, payload: Dict[str, Any]) -> requests.Response:
        return call_ai_service(self._translation, self._translation_url, json=payload, timeout=30)

    def synthesize(self, payload: Dict[str, Any], *, timeout: float) -> requests.Response:
        return call_ai_service(
            self._tts, self._tts_url, served=_tts_served_audio, json=payload, timeout=timeout
        )
