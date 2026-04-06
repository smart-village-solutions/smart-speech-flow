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

# === Standard- und Third-Party-Module ===
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CollectorRegistry, Counter

from .rate_limiter import RateLimitMiddleware

# === Service-URLs für die Orchestrierung ===
# Je nach Umgebung werden interne Docker- oder lokale URLs verwendet
DOCKER_ENV = os.environ.get("DOCKER_COMPOSE", "1") == "1"
DEFAULT_INTERNAL_SCHEME = os.environ.get("SERVICE_SCHEME", "http")
DEFAULT_LOCAL_SCHEME = os.environ.get("LOCAL_SERVICE_SCHEME", DEFAULT_INTERNAL_SCHEME)


def _build_service_base_url(host: str, port: int, *, scheme: str) -> str:
    return f"{scheme}://{host}:{port}"


def _build_service_url(host: str, port: int, path: str, *, scheme: str) -> str:
    return f"{_build_service_base_url(host, port, scheme=scheme)}{path}"


def _localhost_origin(port: int, *, secure: bool = False) -> str:
    protocol = "https" if secure else "http"
    return f"{protocol}://localhost:{port}"


if DOCKER_ENV:
    # Docker-Service-URLs für Microservices
    SERVICE_URLS = {
        "ASR": _build_service_url(
            "asr", 8000, "/health", scheme=DEFAULT_INTERNAL_SCHEME
        ),
        "Translation": _build_service_url(
            "translation", 8000, "/health", scheme=DEFAULT_INTERNAL_SCHEME
        ),
        "TTS": _build_service_url(
            "tts", 8000, "/health", scheme=DEFAULT_INTERNAL_SCHEME
        ),
    }
else:
    # Lokale Service-URLs für Entwicklung ohne Docker
    SERVICE_URLS = {
        "ASR": _build_service_url(
            "localhost", 8001, "/health", scheme=DEFAULT_LOCAL_SCHEME
        ),
        "Translation": _build_service_url(
            "localhost", 8002, "/health", scheme=DEFAULT_LOCAL_SCHEME
        ),
        "TTS": _build_service_url(
            "localhost", 8003, "/health", scheme=DEFAULT_LOCAL_SCHEME
        ),
    }


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


async def websocket_monitor_task() -> None:
    """Background Task für WebSocket-Monitoring und Cleanup"""
    # Verwende den bereits initialisierten Monitor statt neuen zu erstellen
    # Warte bis der Monitor im Startup initialisiert wurde
    await asyncio.sleep(1)  # Kurz warten bis Startup abgeschlossen

    from .websocket_monitor import get_websocket_monitor

    try:
        print("🚀 WebSocket-Monitoring gestartet")
        monitor = get_websocket_monitor()
        await monitor.periodic_cleanup()
    except Exception as e:
        print(f"⚠️ Fehler im WebSocket-Monitor: {e}")


async def websocket_fallback_task() -> None:
    """Background Task für WebSocket-Fallback-System"""
    from .websocket_fallback import fallback_manager

    try:
        print("🔄 WebSocket-Fallback-System gestartet")
        await fallback_manager.periodic_cleanup()
    except Exception as e:
        print(f"⚠️ Fehler im WebSocket-Fallback-System: {e}")


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


async def audio_cleanup_task() -> None:
    """Background Task für automatisches Löschen alter Audio-Dateien (24h Retention)"""
    from .audio_storage import cleanup_old_audio_files, get_disk_usage

    try:
        print("🧹 Audio-Cleanup-Service gestartet (läuft stündlich)")

        while True:
            try:
                # Stündliche Cleanup-Routine
                await asyncio.sleep(3600)  # 1 Stunde warten

                # Cleanup durchführen
                stats = cleanup_old_audio_files()
                print(
                    f"🧹 Audio-Cleanup abgeschlossen: {stats['total_deleted']} Dateien gelöscht"
                )

                # Disk Usage loggen
                disk_stats = get_disk_usage()
                total_mb = disk_stats["total_bytes"] / (1024 * 1024)
                print(
                    f"💾 Audio Storage: {disk_stats['total_files']} Dateien, {total_mb:.2f} MB"
                )

            except Exception as e:
                print(f"⚠️ Fehler im Audio-Cleanup-Task: {e}")
                await asyncio.sleep(3600)
    except Exception as e:
        print(f"❌ Audio-Cleanup-Task Startup Fehler: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application Lifespan: Initialize singletons and start background tasks"""
    import sys

    sys.stderr.write("=" * 80 + "\n")
    sys.stderr.flush()
    sys.stderr.write("API GATEWAY STARTUP\n")
    sys.stderr.flush()
    sys.stderr.write("=" * 80 + "\n")
    sys.stderr.flush()

    # Initialize WebSocketManager singleton
    from .websocket import get_websocket_manager

    sys.stderr.write("Initializing WebSocketManager singleton...\n")
    sys.stderr.flush()
    manager = get_websocket_manager()
    sys.stderr.write(f"WebSocketManager ready (ID: {id(manager)})\n")
    sys.stderr.flush()

    # Start background tasks
    timeout_task = asyncio.create_task(session_timeout_monitor())
    circuit_breaker_task = asyncio.create_task(circuit_breaker_monitor())
    websocket_monitor_bg_task = asyncio.create_task(websocket_monitor_task())
    websocket_fallback_bg_task = asyncio.create_task(websocket_fallback_task())
    audio_cleanup_bg_task = asyncio.create_task(audio_cleanup_task())
    sys.stderr.write("All background tasks started\n")
    sys.stderr.flush()
    sys.stderr.write("=" * 80 + "\n")
    sys.stderr.flush()

    try:
        yield None
    finally:
        from .circuit_breaker_client import circuit_breaker_client

        timeout_task.cancel()
        circuit_breaker_task.cancel()
        websocket_monitor_bg_task.cancel()
        websocket_fallback_bg_task.cancel()
        audio_cleanup_bg_task.cancel()

        try:
            await circuit_breaker_client.stop_health_monitoring()
        except Exception as e:
            print(f"Error stopping circuit breaker: {e}")

        task_results = await asyncio.gather(
            timeout_task,
            circuit_breaker_task,
            websocket_monitor_bg_task,
            websocket_fallback_bg_task,
            audio_cleanup_bg_task,
            return_exceptions=True,
        )

        for result in task_results:
            if isinstance(result, Exception) and not isinstance(
                result, asyncio.CancelledError
            ):
                print(f"Background task shutdown error: {result}")

        print("Shutdown complete", flush=True)


# === App-Initialisierung ===
app = FastAPI(
    title="Smart Speech Flow API Gateway",
    description="""
    Echtzeit-Sprachverarbeitung und Übersetzung mit WebSocket-Unterstützung.

    ## Session Workflow

    1. **Admin** erstellt Session via `/api/admin/session/create`
    2. **Customer** aktiviert Session via `/api/customer/session/activate`
    3. Beide verbinden sich via WebSocket `/ws/{session_id}/{connection_type}`
    4. Nachrichten werden bidirektional übersetzt und zugestellt

    ## Connection Types

    - `admin`: Deutschsprachiger Mitarbeiter (administrative staff member)
    - `customer`: Mehrsprachiger Kunde/Bürger (multilingual end-user/citizen)

    ## WebSocket Architecture

    Das System verwendet einen zentralen **WebSocketManager** als Singleton:
    - Eine Instanz verwaltet alle Verbindungen
    - Dependency Injection via `get_websocket_manager()`
    - Differenzierte Broadcasts (Admin ≠ Customer Nachricht)
    - Prometheus Metrics für Monitoring
    """,
    version="1.1.0",
    lifespan=lifespan,
)


# === Monitoring Setup (BEFORE any module imports) ===
# Eigene Registry erstellen um doppelte Registrierung zu vermeiden
registry = CollectorRegistry()
requests_total = Counter(
    "gateway_requests_total", "Total API Gateway requests", registry=registry
)
requests_total.inc(0)

# Attach to app state
app.state.prometheus_registry = registry
app.state.gateway_requests_total = requests_total
setattr(app, "requests_total", requests_total)


# === WebSocket Monitor Initialisierung ===
# Muss VOR dem Import der WebSocket-Module passieren
from .websocket_monitor import initialize_websocket_monitor

websocket_monitor = initialize_websocket_monitor(registry)


# === CORS Middleware ===
# Enhanced CORS Configuration for WebSocket Support
def setup_cors_for_websockets():
    """Configure CORS for both REST API and WebSocket connections"""
    # Development vs Production CORS
    development_origins = os.environ.get("DEVELOPMENT_CORS_ORIGINS", "").split(",")
    development_origins = [
        origin.strip() for origin in development_origins if origin.strip()
    ]

    production_pattern = (
        r"https://.*\.figma\.site|https://translate\.smart-village\.solutions"
    )
    environment = os.environ.get("ENVIRONMENT", "production")

    if environment == "development":
        # Allow localhost and configured development origins
        allow_origins = development_origins + [
            _localhost_origin(3000),
            _localhost_origin(3001),
            _localhost_origin(8080),
            _localhost_origin(3000, secure=True),
            _localhost_origin(3001, secure=True),
            _localhost_origin(8080, secure=True),
        ]
        allow_origin_regex = None
    else:
        # Production: strict validation
        allow_origins = []
        allow_origin_regex = production_pattern

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_origin_regex=allow_origin_regex,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"],
        allow_headers=[
            # Standard headers
            "Content-Type",
            "Authorization",
            "Accept",
            "Origin",
            "User-Agent",
            "Cache-Control",
            "Pragma",
            # WebSocket-specific headers
            "Upgrade",
            "Connection",
            "Sec-WebSocket-Key",
            "Sec-WebSocket-Version",
            "Sec-WebSocket-Protocol",
            "Sec-WebSocket-Extensions",
        ],
        expose_headers=[
            "Content-Length",
            "Content-Type",
            # WebSocket upgrade response headers
            "Upgrade",
            "Connection",
            "Sec-WebSocket-Accept",
        ],
    )


# Setup CORS with WebSocket support
setup_cors_for_websockets()


# === Rate Limiting Middleware ===
app.add_middleware(RateLimitMiddleware)


# === Module Imports (AFTER app initialization) ===
from . import websocket, websocket_monitoring_routes, websocket_polling_routes
from .routes import admin, circuit_breaker, customer, session
from .routes.metrics import metrics

# === Session-Routen registrieren ===
app.include_router(session.router, prefix="/api", tags=["sessions"])
app.include_router(admin.router, tags=["admin"])
app.include_router(customer.router, tags=["customer"])
app.include_router(websocket_monitoring_routes.router, tags=["websocket-monitoring"])
app.include_router(websocket_polling_routes.router, tags=["websocket-polling-fallback"])
app.include_router(websocket.router, tags=["websocket"])
app.include_router(circuit_breaker.router, prefix="/api", tags=["circuit-breaker"])

# Metrics-Route direkt an App binden
app.get("/metrics")(metrics)


@app.get("/languages", tags=["public"], summary="List supported languages")
async def list_supported_languages() -> Any:
    """Expose supported languages without the /api prefix for the public site."""
    return await session.get_supported_languages()


# === Lokaler Start ===
# Startet die App direkt mit "python app.py" (für Entwicklung und Debugging)
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host=os.environ.get("SSF_LOCAL_BIND_HOST", "127.0.0.1"),
        port=8000,
        reload=True,
    )
