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
import sys
import threading
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

# === Standard- und Third-Party-Module ===
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CollectorRegistry, Counter

from .client_origin import configured_client_origin
from .pipeline_admission import (
    PipelineAdmission,
    PipelineAdmissionConfig,
    PipelineAdmissionMetrics,
)
from .rate_limiter import RateLimitMiddleware

# === Service-URLs für die Orchestrierung ===
# Je nach Umgebung werden interne Docker- oder lokale URLs verwendet
DOCKER_ENV = os.environ.get("DOCKER_COMPOSE", "1") == "1"
DEFAULT_INTERNAL_SCHEME = os.environ.get("SERVICE_SCHEME", "http")
DEFAULT_LOCAL_SCHEME = os.environ.get("LOCAL_SERVICE_SCHEME", DEFAULT_INTERNAL_SCHEME)
HEALTH_PATH = "/health"


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
        "ASR": _build_service_url("asr", 8000, HEALTH_PATH, scheme=DEFAULT_INTERNAL_SCHEME),
        "Translation": _build_service_url(
            "translation", 8000, HEALTH_PATH, scheme=DEFAULT_INTERNAL_SCHEME
        ),
        "TTS": _build_service_url("tts", 8000, HEALTH_PATH, scheme=DEFAULT_INTERNAL_SCHEME),
    }
else:
    # Lokale Service-URLs für Entwicklung ohne Docker
    SERVICE_URLS = {
        "ASR": _build_service_url("localhost", 8001, HEALTH_PATH, scheme=DEFAULT_LOCAL_SCHEME),
        "Translation": _build_service_url(
            "localhost", 8002, HEALTH_PATH, scheme=DEFAULT_LOCAL_SCHEME
        ),
        "TTS": _build_service_url("localhost", 8003, HEALTH_PATH, scheme=DEFAULT_LOCAL_SCHEME),
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
                print(f"🧹 Audio-Cleanup abgeschlossen: {stats['total_deleted']} Dateien gelöscht")

                # Disk Usage loggen
                disk_stats = get_disk_usage()
                total_mb = disk_stats["total_bytes"] / (1024 * 1024)
                print(f"💾 Audio Storage: {disk_stats['total_files']} Dateien, {total_mb:.2f} MB")

            except Exception as e:
                print(f"⚠️ Fehler im Audio-Cleanup-Task: {e}")
                await asyncio.sleep(3600)
    except Exception as e:
        print(f"❌ Audio-Cleanup-Task Startup Fehler: {e}")


FEEDBACK_RECONCILIATION_INTERVAL_SECONDS = 300
FEEDBACK_RETENTION_INTERVAL_SECONDS = 3600
FEEDBACK_CONNECT_RETRY_SECONDS = 5
FEEDBACK_CONNECT_RETRY_CEILING_SECONDS = 60


def _feedback_password(variable: str) -> str | None:
    """The password arrives beside the DSN, never inside it.

    A generated password is not URL-safe: see
    PostgresFeedbackRepository.create.
    """
    return os.environ.get(variable, "").strip() or None


async def _connect_feedback_request_path(dsn: str, sessions: Any) -> bool:
    """Wire POST /api/feedback. Returns False only when retrying could help."""
    if app.state.feedback_service is not None:
        return True

    # Imported inside their own guard: crypto.py depends on `cryptography`,
    # which reaches the image only as PyJWT's `[crypto]` extra. An ImportError
    # escaping this function would propagate through the lifespan and stop the
    # gateway booting -- turning a missing feedback dependency into a total
    # outage, which is the opposite of what this whole path promises. It has
    # to be its own block, because the handler below names an exception this
    # import is what binds.
    try:
        from .feedback.crypto import FeedbackCipher, MissingEncryptionKey
        from .feedback.repository import PostgresFeedbackRepository
        from .feedback.service import FeedbackService
        from .feedback.tenant import ConfiguredTenantResolver
    except ImportError as error:
        sys.stderr.write(
            f"Feedback persistence disabled: {type(error).__name__}; "
            "POST /api/feedback will answer 503\n"
        )
        return True

    try:
        cipher = FeedbackCipher.from_environment()
    except MissingEncryptionKey:
        # Terminal, not transient: no key appears later, and encrypting under
        # a generated one would store rows nobody could ever read back.
        sys.stderr.write(
            "Feedback persistence disabled: SSF_FEEDBACK_ENCRYPTION_KEY is missing "
            "or malformed; POST /api/feedback will answer 503\n"
        )
        return True

    try:
        repository = await PostgresFeedbackRepository.create(
            dsn=dsn, password=_feedback_password("SSF_FEEDBACK_DATABASE_PASSWORD")
        )
    except Exception as error:  # noqa: BLE001 - reported, not raised
        # Type name only: a connection error can carry the DSN, and the DSN
        # carries the database password.
        sys.stderr.write(
            f"Feedback persistence unavailable ({type(error).__name__}); "
            "POST /api/feedback will answer 503 until it connects\n"
        )
        return False

    app.state.feedback_repository = repository
    app.state.feedback_service = FeedbackService(
        repository=repository,
        cipher=cipher,
        tenant_resolver=ConfiguredTenantResolver.from_environment(),
        session_manager=sessions,
        telemetry=app.state.quality_telemetry,
    )
    sys.stderr.write("Feedback persistence ready\n")
    return True


async def _connect_feedback_maintenance(dsn: str) -> bool:
    """Wire the recovery and retention passes, reporting on their own.

    Separate from the request path in both directions: collecting feedback
    matters more than reconciling it, and a maintenance pool that never opens
    must not be announced as an endpoint outage.
    """
    if app.state.feedback_maintenance is not None:
        return True
    if not dsn:
        sys.stderr.write(
            "Feedback maintenance disabled: SSF_FEEDBACK_MAINTENANCE_DATABASE_URL "
            "is not set; analytics recovery and retention will not run\n"
        )
        return True

    from .feedback.maintenance import FeedbackMaintenance, FeedbackMaintenanceMetrics
    from .feedback.repository import PostgresFeedbackRepository

    try:
        repository = await PostgresFeedbackRepository.create(
            dsn=dsn,
            password=_feedback_password("SSF_FEEDBACK_MAINTENANCE_DATABASE_PASSWORD"),
        )
    except Exception as error:  # noqa: BLE001 - reported, not raised
        sys.stderr.write(
            f"Feedback maintenance unavailable ({type(error).__name__}); "
            "analytics recovery and retention are not running. "
            "POST /api/feedback is unaffected\n"
        )
        return False

    app.state.feedback_maintenance_repository = repository
    app.state.feedback_maintenance = FeedbackMaintenance(
        repository=repository,
        telemetry=app.state.quality_telemetry,
        metrics=FeedbackMaintenanceMetrics(app.state.prometheus_registry),
    )
    sys.stderr.write("Feedback maintenance ready\n")
    return True


async def _wire_feedback(request_dsn: str, maintenance_dsn: str, sessions: Any) -> bool:
    """Wire both halves. Returns False only when retrying could help.

    The two are reached independently on purpose. Unsetting
    SSF_FEEDBACK_DATABASE_URL is the documented way to stop accepting feedback
    while keeping the database, and the rows already stored still carry a
    twelve-month expiry that the submission notice promises in ten languages.
    Gating the passes on the submission path would stop enforcing it with no
    code path having decided to.
    """
    if not request_dsn:
        sys.stderr.write(
            "Feedback persistence disabled: SSF_FEEDBACK_DATABASE_URL is not set; "
            "POST /api/feedback will answer 503\n"
        )
        connected = True
    else:
        connected = await _connect_feedback_request_path(request_dsn, sessions)

    maintained = await _connect_feedback_maintenance(maintenance_dsn)
    sys.stderr.flush()
    return connected and maintained


async def feedback_connect_task(request_dsn: str, maintenance_dsn: str, sessions: Any) -> None:
    """Keep retrying whichever half did not connect at startup.

    The gateway deliberately does not wait for a healthy feedback database --
    a failed migration must not cost every customer their session -- so on a
    first deploy the database is usually still running its init scripts when
    this process starts. Nothing else retries, so without this that ordinary
    race leaves POST /api/feedback answering 503 until someone restarts the
    container.
    """
    if not request_dsn and not maintenance_dsn:
        return

    delay = FEEDBACK_CONNECT_RETRY_SECONDS
    while True:
        try:
            await asyncio.sleep(delay)
            delay = min(delay * 2, FEEDBACK_CONNECT_RETRY_CEILING_SECONDS)

            if await _wire_feedback(request_dsn, maintenance_dsn, sessions):
                return
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - the loop must outlive it
            print(f"\u26a0\ufe0f Feedback connection attempt failed: {type(error).__name__}")


async def feedback_maintenance_task() -> None:
    """Drive analytics recovery and retention expiry (#305).

    One task for both passes on different periods: reconciliation is a cheap
    indexed read and wants to be prompt, while deletion is neither and only
    one replica performs it per pass anyway.

    Nothing here raises. FeedbackMaintenance already contains its own failures,
    and the loop is guarded besides: a task that dies takes every future pass
    with it, which is how retention silently stops being enforced.
    """
    elapsed = 0

    while True:
        try:
            await asyncio.sleep(FEEDBACK_RECONCILIATION_INTERVAL_SECONDS)
            elapsed += FEEDBACK_RECONCILIATION_INTERVAL_SECONDS

            maintenance = getattr(app.state, "feedback_maintenance", None)
            if maintenance is None:
                continue

            await maintenance.reconcile_once()

            if elapsed >= FEEDBACK_RETENTION_INTERVAL_SECONDS:
                elapsed = 0
                await maintenance.expire_once()
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - the loop must outlive it
            print(f"\u26a0\ufe0f Feedback maintenance pass failed: {type(error).__name__}")


# Well inside Docker's 10s stop grace: telemetry is the least important thing
# still holding the process open at teardown.
QUALITY_TELEMETRY_SHUTDOWN_TIMEOUT_SECONDS = 2.0


async def _shutdown_quality_telemetry(exporter: Any, timeout_seconds: float) -> None:
    """Tear the OTLP exporter down off the event loop, on a bounded budget.

    A daemon thread rather than `asyncio.to_thread`: the SDK's shutdown joins
    its own export thread for a default 30s while it drains the queue, and a
    `to_thread` worker cannot be abandoned — the loop's teardown joins the
    default executor with a 300s timeout of its own. A collector that accepts
    the connection and never answers would otherwise outlast Docker's 10s stop
    grace and read as a hung container.
    """
    failures: list[BaseException] = []

    def run() -> None:
        try:
            exporter.shutdown()
        except Exception as e:  # reported at teardown, never raised to the loop
            failures.append(e)

    thread = threading.Thread(target=run, name="quality-telemetry-shutdown", daemon=True)
    thread.start()

    deadline = time.monotonic() + timeout_seconds
    while thread.is_alive() and time.monotonic() < deadline:
        await asyncio.sleep(0.05)

    if thread.is_alive():
        print("Quality telemetry shutdown timed out; export thread abandoned")
    elif failures:
        print(f"Error stopping quality telemetry: {failures[0]}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application Lifespan: Initialize singletons and start background tasks"""

    sys.stderr.write("=" * 80 + "\n")
    sys.stderr.flush()
    sys.stderr.write("API GATEWAY STARTUP\n")
    sys.stderr.flush()
    sys.stderr.write("=" * 80 + "\n")
    sys.stderr.flush()

    # The v2 session record, tenant indexes, join tombstone, and single-use
    # realtime ticket must share one verified Redis connection in production.
    # This happens before any WebSocket manager or background task can observe
    # process-local tenant state.
    from .tenant_persistence import configure_tenant_persistence

    tenant_persistence = configure_tenant_persistence()

    # Initialize WebSocketManager singleton
    from .websocket import get_websocket_manager

    sys.stderr.write("Initializing WebSocketManager singleton...\n")
    sys.stderr.flush()
    manager = get_websocket_manager()
    sys.stderr.write(f"WebSocketManager ready (ID: {id(manager)})\n")
    sys.stderr.flush()

    # Bounded admission for GPU pipeline work (#191). Owned by the lifespan so
    # the semaphore belongs to this running app rather than to import time.
    admission_config = PipelineAdmissionConfig()
    app.state.pipeline_admission = PipelineAdmission(
        admission_config, metrics=pipeline_admission_metrics
    )
    sys.stderr.write(
        "Pipeline admission ready "
        f"(max_concurrent={admission_config.max_concurrent}, "
        f"queue_wait_seconds={admission_config.queue_wait_seconds})\n"
    )
    sys.stderr.flush()

    from .quality_telemetry import QualityTelemetry, TelemetryMode, discard_event
    from .quality_telemetry_otlp import build_otlp_exporter

    telemetry_mode = TelemetryMode.parse(os.environ.get("SSF_QUALITY_TELEMETRY_MODE"))
    # Built only when it will be used: the SDK provider runs a worker thread.
    telemetry_exporter = None
    quality_telemetry = None
    try:
        if telemetry_mode is not TelemetryMode.DISABLED:
            telemetry_exporter = build_otlp_exporter(
                endpoint=os.environ.get(
                    "SSF_OTLP_LOGS_ENDPOINT", "http://otel-collector:4318/v1/logs"
                ),
                service_name="api_gateway",
                service_version=os.environ.get("SSF_RELEASE_VERSION", "unknown"),
                deployment_environment=os.environ.get("SSF_DEPLOYMENT_ENV", "unknown"),
            )
        quality_telemetry = QualityTelemetry(
            mode=telemetry_mode,
            exporter=telemetry_exporter or discard_event,
            registry=app.state.prometheus_registry,
        )
    except Exception as e:
        # OTLPLogExporter parses OTEL_EXPORTER_OTLP_TIMEOUT and _COMPRESSION
        # itself and raises on a malformed value, and QualityTelemetry has to
        # register a Prometheus counter. Same rule as TelemetryMode.parse: fall
        # back to disabled rather than crashloop the gateway over an optional
        # setting. Reported as disabled, not as a silent probe mode that
        # exports nothing.
        sys.stderr.write(f"Quality telemetry disabled: setup failed ({e})\n")
        sys.stderr.flush()
        telemetry_mode = TelemetryMode.DISABLED
        telemetry_exporter = None

    if quality_telemetry is None:
        # Last resort: an unregistered registry cannot collide with anything,
        # so this construction has nothing left to fail on.
        quality_telemetry = QualityTelemetry(
            mode=TelemetryMode.DISABLED,
            exporter=discard_event,
            registry=CollectorRegistry(),
        )

    app.state.quality_telemetry_exporter = telemetry_exporter
    app.state.quality_telemetry = quality_telemetry
    # The refiner and the session manager are module-level singletons built at
    # import time; telemetry is built here, per lifespan. Nothing connects them
    # unless these lines do.
    from .session_manager import session_manager
    from .translation_refiner import translation_refiner

    translation_refiner.attach_quality_telemetry(app.state.quality_telemetry)
    session_manager.attach_quality_telemetry(app.state.quality_telemetry)
    # Rehydrated sessions must enforce reconnect and absolute deadlines before
    # the lifespan yields and the gateway can accept a request.
    await session_manager.check_session_timeouts()
    sys.stderr.write(f"Quality telemetry ready (mode={telemetry_mode.value})\n")
    sys.stderr.flush()

    # Feedback persistence (#302). Deliberately non-fatal: the gateway serves
    # the whole conversation pipeline, and an unreachable feedback database
    # must cost submissions a retryable 503 rather than cost every customer
    # their session. That is also why Compose starts this service without
    # waiting for the database to be healthy -- which makes losing the race a
    # normal first-deploy event, so feedback_connect_task keeps retrying.
    app.state.feedback_repository = None
    app.state.feedback_maintenance_repository = None
    app.state.feedback_service = None
    app.state.feedback_maintenance = None
    feedback_dsn = os.environ.get("SSF_FEEDBACK_DATABASE_URL", "").strip()
    # Reconciliation and retention are deployment-wide, so they connect as a
    # role the tenant policy does not filter -- see deploy/postgres/migrations/
    # 002_feedback_roles.sql. Sharing the request pool would leave both passes
    # seeing no rows and reporting success.
    maintenance_dsn = os.environ.get("SSF_FEEDBACK_MAINTENANCE_DATABASE_URL", "").strip()
    await _wire_feedback(feedback_dsn, maintenance_dsn, session_manager)

    # Start background tasks
    timeout_task = asyncio.create_task(session_timeout_monitor())
    circuit_breaker_task = asyncio.create_task(circuit_breaker_monitor())
    websocket_monitor_bg_task = asyncio.create_task(websocket_monitor_task())
    websocket_fallback_bg_task = asyncio.create_task(websocket_fallback_task())
    audio_cleanup_bg_task = asyncio.create_task(audio_cleanup_task())
    feedback_maintenance_bg_task = asyncio.create_task(feedback_maintenance_task())
    feedback_connect_bg_task = asyncio.create_task(
        feedback_connect_task(feedback_dsn, maintenance_dsn, session_manager)
    )
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
        feedback_maintenance_bg_task.cancel()
        feedback_connect_bg_task.cancel()

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
            feedback_maintenance_bg_task,
            feedback_connect_bg_task,
            return_exceptions=True,
        )

        for result in task_results:
            if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                print(f"Background task shutdown error: {result}")

        app.state.pipeline_admission = None

        # Released before the provider is shut down: a holder still using this
        # would emit into a provider that no longer has an export thread.
        translation_refiner.attach_quality_telemetry(None)
        session_manager.attach_quality_telemetry(None)
        if tenant_persistence is not None:
            tenant_persistence.close()
        telemetry_exporter_at_exit = app.state.quality_telemetry_exporter
        app.state.quality_telemetry_exporter = None
        if telemetry_exporter_at_exit is not None:
            await _shutdown_quality_telemetry(
                telemetry_exporter_at_exit,
                QUALITY_TELEMETRY_SHUTDOWN_TIMEOUT_SECONDS,
            )

        feedback_repository_at_exit = getattr(app.state, "feedback_repository", None)
        feedback_maintenance_repository_at_exit = getattr(
            app.state, "feedback_maintenance_repository", None
        )
        app.state.feedback_repository = None
        app.state.feedback_maintenance_repository = None
        app.state.feedback_service = None
        app.state.feedback_maintenance = None
        for pool_at_exit in (
            feedback_repository_at_exit,
            feedback_maintenance_repository_at_exit,
        ):
            if pool_at_exit is not None:
                await pool_at_exit.close()

        print("Shutdown complete", flush=True)


# === App-Initialisierung ===
app = FastAPI(
    title="Smart Speech Flow API Gateway",
    description="""
    Echtzeit-Sprachverarbeitung und Übersetzung mit WebSocket-Unterstützung.

    ## Session Workflow

    1. **Admin** erstellt Session via `/api/admin/session/create`
    2. **Customer** aktiviert Session via `/api/customer/session/activate`
    3. Beide beziehen ein kurzlebiges Realtime-Ticket und verbinden sich über
       ihren rollenspezifischen WebSocket-Endpunkt
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
requests_total = Counter("gateway_requests_total", "Total API Gateway requests", registry=registry)
requests_total.inc(0)

# Registered here rather than in the lifespan because a Prometheus series may be
# created only once per registry, while the admission component itself is rebuilt
# per lifespan.
pipeline_admission_metrics = PipelineAdmissionMetrics(registry)

# Attach to app state
app.state.prometheus_registry = registry
app.state.gateway_requests_total = requests_total
setattr(app, "requests_total", requests_total)


# === WebSocket Monitor Initialisierung ===
# Muss VOR dem Import der WebSocket-Module passieren
from .websocket_monitor import initialize_websocket_monitor

websocket_monitor = initialize_websocket_monitor(registry)

# The fallback manager is a module-level singleton built before this registry
# exists; without this its drop counter would sit on prometheus_client's global
# default registry, which /metrics does not serve.
from .websocket_fallback import fallback_manager

fallback_manager.bind_metrics_registry(registry)

from .websocket_polling_routes import polling_store

polling_store.bind_metrics_registry(registry)


# === CORS Middleware ===
# Enhanced CORS Configuration for WebSocket Support
def setup_cors_for_websockets():
    """Configure CORS for both REST API and WebSocket connections"""
    # Development vs Production CORS
    development_origins = os.environ.get("DEVELOPMENT_CORS_ORIGINS", "").split(",")
    development_origins = [origin.strip() for origin in development_origins if origin.strip()]

    production_pattern = r"https://.*\.figma\.site|https://translate\.smart-village\.solutions"
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
        client_origin = configured_client_origin()
        allow_origins = [client_origin] if client_origin else []
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
            "X-Correlation-Id",
            "X-SSF-Legacy-Access",
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
from .routes import admin, circuit_breaker, customer, feedback, login, session
from .routes.metrics import metrics

# === Session-Routen registrieren ===
app.include_router(session.router, prefix="/api", tags=["sessions"])
app.include_router(login.router)
app.include_router(admin.router, tags=["admin"])
app.include_router(customer.router, tags=["customer"])
app.include_router(websocket_monitoring_routes.router, tags=["websocket-monitoring"])
app.include_router(websocket_polling_routes.router, tags=["websocket-polling-fallback"])
app.include_router(websocket.router, tags=["websocket"])
app.include_router(circuit_breaker.router, prefix="/api", tags=["circuit-breaker"])
app.include_router(feedback.router, tags=["feedback"])

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
