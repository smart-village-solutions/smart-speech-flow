"""
API Gateway Hauptdatei
- Initialisiert die FastAPI-App
- Konfiguriert CORS und Monitoring
- Definiert Service-URLs für die Orchestrierung
- Importiert alle Endpunkte zentral
- Ermöglicht lokalen Start mit Uvicorn
"""

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

# === Imports ===
# Standard- und Third-Party-Module
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CollectorRegistry, Counter

from .rate_limiter import RateLimitMiddleware


# === Background Tasks ===
async def session_timeout_monitor() -> None:
    """Background Task für Session-Timeout-Management"""
    from .session_manager import session_manager

    while True:
        try:
            await session_manager.check_session_timeouts()
            await asyncio.sleep(60)  # Alle 60 Sekunden prüfen
        except Exception as e:
            print(f"⚠️ Fehler im Session-Timeout-Monitor: {e}")
            await asyncio.sleep(60)


async def circuit_breaker_monitor() -> None:
    """Background Task für Circuit Breaker Health Monitoring"""
    from .circuit_breaker_client import circuit_breaker_client
    from .graceful_degradation import graceful_degradation_manager

    try:
        # Health Monitoring starten
        await circuit_breaker_client.start_health_monitoring()
        print("🚀 Circuit Breaker Health Monitoring gestartet")

        # Cleanup Loop für expired cache entries
        while True:
            try:
                await graceful_degradation_manager.cleanup_expired_cache()
                await graceful_degradation_manager.process_pending_requests()
                await asyncio.sleep(300)  # Alle 5 Minuten
            except Exception as e:
                print(f"⚠️ Fehler im Circuit Breaker Monitor: {e}")
                await asyncio.sleep(300)
    except Exception as e:
        print(f"❌ Circuit Breaker Monitor Startup Fehler: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup: Background Tasks starten
    timeout_task = asyncio.create_task(session_timeout_monitor())
    circuit_breaker_task = asyncio.create_task(circuit_breaker_monitor())

    try:
        yield None
    finally:
        # Shutdown: Background Tasks beenden
        from .circuit_breaker_client import circuit_breaker_client

        timeout_task.cancel()
        circuit_breaker_task.cancel()

        # Circuit Breaker Health Monitoring stoppen
        try:
            await circuit_breaker_client.stop_health_monitoring()
        except Exception as e:
            print(f"⚠️ Fehler beim Stoppen des Circuit Breaker Monitoring: {e}")

        # Tasks aufräumen
        for task in [timeout_task, circuit_breaker_task]:
            try:
                await task
            except asyncio.CancelledError:
                pass


# === App-Initialisierung ===
app = FastAPI(title="API Gateway", lifespan=lifespan)

# === CORS Middleware ===
# Erlaubt Zugriffe von Figma-Subdomains und der Produktiv-Domain
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https://.*\.figma\.site|https://translate\.smart-village\.solutions",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Rate Limiting Middleware ===
app.add_middleware(RateLimitMiddleware)

# === Monitoring ===
# Eigene Registry, um doppelte Registrierung zu vermeiden
registry = CollectorRegistry()
requests_total = Counter(
    "gateway_requests_total", "Total API Gateway requests", registry=registry
)
requests_total.inc(0)
app.state.prometheus_registry = registry
app.state.gateway_requests_total = requests_total
setattr(app, "requests_total", requests_total)

# === Service-URLs für die Orchestrierung ===
# Je nach Umgebung werden interne Docker- oder lokale URLs verwendet
DOCKER_ENV = os.environ.get("DOCKER_COMPOSE", "1") == "1"

if DOCKER_ENV:
    # Docker-Service-URLs für Microservices
    ASR_URL: str = "http://asr:8000/transcribe"
    TRANSLATION_URL: str = "http://translation:8000/translate"
    TTS_URL: str = "http://tts:8000/synthesize"
    SERVICE_URLS = {
        "ASR": "http://asr:8000/health",
        "Translation": "http://translation:8000/health",
        "TTS": "http://tts:8000/health",
    }
else:
    # Lokale Service-URLs für Entwicklung ohne Docker
    ASR_URL = "http://localhost:8101/transcribe"
    TRANSLATION_URL = "http://localhost:8102/translate"
    TTS_URL = "http://localhost:8103/synthesize"
    SERVICE_URLS = {
        "ASR": "http://localhost:8101/health",
        "Translation": "http://localhost:8102/health",
        "TTS": "http://localhost:8103/health",
    }

from . import websocket

# === Routen-Import ===
# Importiert alle FastAPI-Endpunkte zentral aus dem routes-Paket
from .routes import admin, circuit_breaker, customer, session

# === Session-Routen registrieren ===
app.include_router(session.router, prefix="/api", tags=["sessions"])
app.include_router(admin.router, tags=["admin"])
app.include_router(customer.router, tags=["customer"])
app.include_router(websocket.router, tags=["websocket"])
app.include_router(circuit_breaker.router, prefix="/api", tags=["circuit-breaker"])


@app.get("/languages", tags=["public"], summary="List supported languages")
async def list_supported_languages() -> Any:
    """Expose supported languages without the /api prefix for the public site."""
    return await session.get_supported_languages()


# === Lokaler Start ===
# Startet die App direkt mit "python app.py" (für Entwicklung und Debugging)
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
