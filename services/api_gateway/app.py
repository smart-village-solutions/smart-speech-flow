"""
API Gateway Hauptdatei
- Initialisiert die FastAPI-App
- Konfiguriert CORS und Monitoring
- Definiert Service-URLs für die Orchestrierung
- Importiert alle Endpunkte zentral
- Ermöglicht lokalen Start mit Uvicorn
"""

# === Imports ===
# Standard- und Third-Party-Module
from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import Response
import requests
import os
from prometheus_client import Counter, generate_latest, CollectorRegistry
import base64
from fastapi.middleware.cors import CORSMiddleware
import asyncio
from contextlib import asynccontextmanager

from .rate_limiter import RateLimitMiddleware

# === Background Tasks ===
async def session_timeout_monitor():
    """Background Task für Session-Timeout-Management"""
    from .session_manager import session_manager

    while True:
        try:
            await session_manager.check_session_timeouts()
            await asyncio.sleep(60)  # Alle 60 Sekunden prüfen
        except Exception as e:
            print(f"⚠️ Fehler im Session-Timeout-Monitor: {e}")
            await asyncio.sleep(60)

async def circuit_breaker_monitor():
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
async def lifespan(app: FastAPI):
    # Startup: Background Tasks starten
    timeout_task = asyncio.create_task(session_timeout_monitor())
    circuit_breaker_task = asyncio.create_task(circuit_breaker_monitor())

    try:
        yield
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
requests_total = Counter('gateway_requests_total', 'Total API Gateway requests', registry=registry)

# === Service-URLs für die Orchestrierung ===
# Je nach Umgebung werden interne Docker- oder lokale URLs verwendet
DOCKER_ENV = os.environ.get("DOCKER_COMPOSE", "1") == "1"

if DOCKER_ENV:
    # Docker-Service-URLs für Microservices
    ASR_URL = "http://asr:8000/transcribe"
    TRANSLATION_URL = "http://translation:8000/translate"
    TTS_URL = "http://tts:8000/synthesize"
    SERVICE_URLS = {
        "ASR": "http://asr:8000/health",
        "Translation": "http://translation:8000/health",
        "TTS": "http://tts:8000/health"
    }
else:
    # Lokale Service-URLs für Entwicklung ohne Docker
    ASR_URL = "http://localhost:8101/transcribe"
    TRANSLATION_URL = "http://localhost:8102/translate"
    TTS_URL = "http://localhost:8103/synthesize"
    SERVICE_URLS = {
        "ASR": "http://localhost:8101/health",
        "Translation": "http://localhost:8102/health",
        "TTS": "http://localhost:8103/health"
    }

# === Routen-Import ===
# Importiert alle FastAPI-Endpunkte zentral aus dem routes-Paket
from .routes import index, upload, pipeline, metrics, health, session, admin, circuit_breaker
from services.api_gateway.utils.health_utils import get_health_status_html
from . import websocket

# === Session-Routen registrieren ===
app.include_router(session.router, prefix="/api", tags=["sessions"])
app.include_router(admin.router, tags=["admin"])
app.include_router(websocket.router, tags=["websocket"])
app.include_router(circuit_breaker.router, prefix="/api", tags=["circuit-breaker"])

# === Lokaler Start ===
# Startet die App direkt mit "python app.py" (für Entwicklung und Debugging)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
