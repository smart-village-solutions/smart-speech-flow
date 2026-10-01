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
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, AsyncIterator

# === Standard- und Third-Party-Module ===
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CollectorRegistry

from .background_tasks import (
    audio_cleanup_task,
    circuit_breaker_monitor,
    session_timeout_monitor,
    websocket_monitor_task,
)
from .branding import DISPLAY_NAME
from .client_origin import configured_client_origin
from .dependencies import GatewayDependencies, build_gateway_dependencies
from .feedback.wiring import (
    _close_feedback,
    _feedback_dsns,
    _wire_feedback,
    feedback_connect_task,
    feedback_maintenance_task,
)
from .gateway_metrics import GatewayMetrics
from .logging_setup import configure_logging
from .pipeline_admission import PipelineAdmission, PipelineAdmissionConfig, PipelineAdmissionMetrics
from .rate_limiter import RateLimitMiddleware, RateLimits
from .refinement_metrics import RefinementMetrics
from .unhandled_errors import UnhandledErrorMiddleware

if TYPE_CHECKING:
    pass
    from .quality_telemetry import QualityTelemetry
    from .quality_telemetry_schema import TelemetryMode
    from .runtime_policy import RuntimePolicyGate
    from .studio_runtime_flow import StudioRuntimeFlow
    from .tenant_persistence import TenantPersistenceBinding
    from .translation_refiner import BaseTranslationRefiner


def _localhost_origin(port: int, *, secure: bool = False) -> str:
    protocol = "https" if secure else "http"
    return f"{protocol}://localhost:{port}"


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


def _report_background_task_shutdown_errors(task_results: list[Any]) -> None:
    """Report task failures without treating expected cancellation as an error."""
    for result in task_results:
        if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
            print(f"Background task shutdown error: {result}")


def _announce(line: str) -> None:
    sys.stderr.write(f"{line}\n")
    sys.stderr.flush()


def _build_runtime_policy(
    registry: CollectorRegistry,
) -> "tuple[StudioRuntimeFlow | None, RuntimePolicyGate | None]":
    """The Studio flow and the persistence gate built on it.

    No gate refuses every write, so a failure to build one is a safe state,
    not a startup error. Studio credentials are absent in local development
    and CI.
    """
    from .runtime_policy import RuntimePolicyGate
    from .runtime_policy_metrics import RuntimePolicyMetrics
    from .studio_runtime_flow import StudioRuntimeFlowError, runtime_flow_from_environment

    try:
        runtime_flow = runtime_flow_from_environment()
    except StudioRuntimeFlowError as error:
        sys.stderr.write(f"Runtime policy gate unbound ({error.code}); persistence refused\n")
        sys.stderr.flush()
        return None, None
    gate = RuntimePolicyGate(runtime_flow.client, metrics=RuntimePolicyMetrics(registry))
    sys.stderr.write("Runtime policy gate ready\n")
    sys.stderr.flush()
    return runtime_flow, gate


def _build_dependencies(
    app: FastAPI,
    persistence: "TenantPersistenceBinding | None",
    runtime_flow: "StudioRuntimeFlow | None",
    runtime_policy: "RuntimePolicyGate | None",
    pipeline: "_PipelineCollaborators",
) -> GatewayDependencies:
    _announce("Building gateway dependencies...")
    metrics: GatewayMetrics = app.state.gateway_metrics
    dependencies = build_gateway_dependencies(
        prometheus_registry=app.state.prometheus_registry,
        redis=persistence.redis if persistence is not None else None,
        redis_namespace=persistence.namespace if persistence is not None else "ssf",
        studio_runtime_flow=runtime_flow,
        runtime_policy=runtime_policy,
        polling_messages_dropped=metrics.polling_messages_dropped,
        websocket_metrics=metrics.websocket,
        audio_storage_metrics=metrics.audio_storage,
        translation_refiner=pipeline.refiner,
        pipeline_admission=pipeline.admission,
        quality_telemetry=pipeline.quality_telemetry,
        quality_telemetry_exporter=pipeline.quality_telemetry_exporter,
    )
    _announce(f"WebSocketManager ready (ID: {id(dependencies.websocket_manager)})")
    return dependencies


def _build_pipeline_admission(metrics: PipelineAdmissionMetrics) -> PipelineAdmission:
    """Bounded admission for GPU pipeline work (#191).

    Owned by the lifespan so the semaphore belongs to this running app rather
    than to import time.
    """
    admission_config = PipelineAdmissionConfig()
    admission = PipelineAdmission(admission_config, metrics=metrics)
    _announce(
        "Pipeline admission ready "
        f"(max_concurrent={admission_config.max_concurrent}, "
        f"queue_wait_seconds={admission_config.queue_wait_seconds})"
    )
    return admission


def _build_quality_telemetry(
    registry: CollectorRegistry,
) -> "tuple[TelemetryMode, QualityTelemetry, Any]":
    """The telemetry mode, the emitter and its exporter, which is None unless it exports."""
    from .quality_telemetry import QualityTelemetry, discard_event
    from .quality_telemetry_otlp import build_otlp_exporter
    from .quality_telemetry_schema import TelemetryMode

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
            registry=registry,
        )
    except Exception as e:
        # OTLPLogExporter parses OTEL_EXPORTER_OTLP_TIMEOUT and _COMPRESSION
        # itself and raises on a malformed value, and QualityTelemetry has to
        # register a Prometheus counter. Same rule as TelemetryMode.parse: fall
        # back to disabled rather than crashloop the gateway over an optional
        # setting. Reported as disabled, not as a silent probe mode that
        # exports nothing.
        _announce(f"Quality telemetry disabled: setup failed ({e})")
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

    return telemetry_mode, quality_telemetry, telemetry_exporter


@dataclass(slots=True)
class _PipelineCollaborators:
    refiner: "BaseTranslationRefiner"
    admission: PipelineAdmission
    telemetry_mode: "TelemetryMode"
    quality_telemetry: "QualityTelemetry"
    quality_telemetry_exporter: Any


def _build_pipeline_collaborators(
    registry: CollectorRegistry,
    admission_metrics: PipelineAdmissionMetrics,
    refiner: "BaseTranslationRefiner",
) -> _PipelineCollaborators:
    """What the container hands the conversation service.

    Built before the container, which injects them.
    """
    admission = _build_pipeline_admission(admission_metrics)
    telemetry_mode, quality_telemetry, exporter = _build_quality_telemetry(registry)
    return _PipelineCollaborators(refiner, admission, telemetry_mode, quality_telemetry, exporter)


async def _attach_quality_telemetry(
    dependencies: GatewayDependencies,
    telemetry_mode: "TelemetryMode",
    refinement_metrics: RefinementMetrics,
) -> None:
    """Connect this app's refiner and session manager to its telemetry."""
    from .translation_refiner import describe_refinement

    refiner = dependencies.speech_pipeline.refiner
    sessions = dependencies.session_manager
    refiner.attach_quality_telemetry(dependencies.quality_telemetry)
    sessions.attach_quality_telemetry(dependencies.quality_telemetry)
    refiner.attach_refinement_metrics(refinement_metrics)
    if refiner.is_active:
        refinement_model_ref = getattr(refiner, "model", None)
        if refinement_model_ref:
            refinement_metrics.pre_create_series(refinement_model_ref)
    _announce(describe_refinement(refiner))
    # Rehydrated sessions must enforce reconnect and absolute deadlines before
    # the lifespan yields and the gateway can accept a request.
    await sessions.check_session_timeouts()
    _announce(f"Quality telemetry ready (mode={telemetry_mode.value})")


def _start_background_tasks(
    dependencies: GatewayDependencies, feedback_dsns: tuple[str, str, str]
) -> list[asyncio.Task[None]]:
    feedback_dsn, maintenance_dsn, read_dsn = feedback_dsns
    sessions = dependencies.session_manager
    return [
        asyncio.create_task(session_timeout_monitor(sessions)),
        asyncio.create_task(circuit_breaker_monitor(dependencies.circuit_breaker_client)),
        asyncio.create_task(
            websocket_monitor_task(dependencies.websocket_monitor, dependencies.websocket_manager)
        ),
        asyncio.create_task(audio_cleanup_task(sessions, dependencies.audio_store)),
        asyncio.create_task(feedback_maintenance_task(dependencies)),
        asyncio.create_task(
            feedback_connect_task(dependencies, feedback_dsn, maintenance_dsn, sessions, read_dsn)
        ),
    ]


async def _shut_down(
    app: FastAPI,
    dependencies: GatewayDependencies,
    tasks: list[asyncio.Task[None]],
    persistence: "TenantPersistenceBinding | None",
) -> None:
    for task in tasks:
        task.cancel()

    try:
        await dependencies.circuit_breaker_client.stop_health_monitoring()
    except Exception as e:
        print(f"Error stopping circuit breaker: {e}")

    task_results = await asyncio.gather(*tasks, return_exceptions=True)
    _report_background_task_shutdown_errors(task_results)
    # Started by the first socket, so it is not among the tasks above.
    await dependencies.websocket_manager.stop_heartbeat_system()

    dependencies.pipeline_admission = None

    # Released before the provider is shut down: a holder still using this
    # would emit into a provider that no longer has an export thread.
    refiner = dependencies.speech_pipeline.refiner
    refiner.attach_quality_telemetry(None)
    dependencies.session_manager.attach_quality_telemetry(None)
    refiner.attach_refinement_metrics(None)
    refiner.shutdown()
    # A handler still holding the manager after shutdown persists nothing.
    dependencies.session_manager.runtime_policy = None
    if persistence is not None:
        persistence.close()
    telemetry_exporter_at_exit = dependencies.quality_telemetry_exporter
    dependencies.quality_telemetry_exporter = None
    if telemetry_exporter_at_exit is not None:
        await _shutdown_quality_telemetry(
            telemetry_exporter_at_exit,
            QUALITY_TELEMETRY_SHUTDOWN_TIMEOUT_SECONDS,
        )

    await _close_feedback(dependencies)
    app.state.dependencies = None

    print("Shutdown complete", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build this app's dependency container, run its background tasks, release both."""

    _announce("=" * 80)
    _announce("API GATEWAY STARTUP")
    _announce("=" * 80)

    # First, as when it ran at import: a malformed LLM_REFINEMENT_* setting
    # raises here and refuses startup before anything connects.
    from .translation_refiner import get_translation_refiner

    refiner = get_translation_refiner()

    # The v2 session record, tenant indexes, join tombstone, and single-use
    # realtime ticket must share one verified Redis connection in production.
    from .tenant_persistence import configure_tenant_persistence

    tenant_persistence = configure_tenant_persistence()
    metrics: GatewayMetrics = app.state.gateway_metrics
    runtime_flow, runtime_policy = _build_runtime_policy(app.state.prometheus_registry)
    pipeline = _build_pipeline_collaborators(
        app.state.prometheus_registry, metrics.pipeline_admission, refiner
    )

    dependencies = _build_dependencies(
        app, tenant_persistence, runtime_flow, runtime_policy, pipeline
    )
    if tenant_persistence is not None:
        # Before any request, socket or background task can see this app's sessions.
        dependencies.session_manager.rehydrate_tenant_sessions()
    app.state.dependencies = dependencies
    await _attach_quality_telemetry(dependencies, pipeline.telemetry_mode, metrics.refinement)

    # Feedback persistence (#302). Deliberately non-fatal: the gateway serves
    # the whole conversation pipeline, and an unreachable feedback database
    # must cost submissions a retryable 503 rather than cost every customer
    # their session. That is also why Compose starts this service without
    # waiting for the database to be healthy -- which makes losing the race a
    # normal first-deploy event, so feedback_connect_task keeps retrying.
    feedback_dsns = _feedback_dsns()
    feedback_dsn, maintenance_dsn, read_dsn = feedback_dsns
    await _wire_feedback(
        dependencies, feedback_dsn, maintenance_dsn, dependencies.session_manager, read_dsn
    )

    tasks = _start_background_tasks(dependencies, feedback_dsns)
    _announce("All background tasks started")
    _announce("=" * 80)

    try:
        yield None
    finally:
        await _shut_down(app, dependencies, tasks, tenant_persistence)


# === CORS Middleware ===
# Enhanced CORS Configuration for WebSocket Support
def setup_cors_for_websockets(app: FastAPI) -> None:
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


# === Module Imports ===
from . import websocket, websocket_monitoring_routes, websocket_polling_routes
from .routes import admin, circuit_breaker, customer, feedback, login, session
from .routes.health import router as health_router
from .routes.metrics import metrics


async def list_supported_languages() -> Any:
    """Expose supported languages without the /api prefix for the public site."""
    return await session.get_supported_languages()


def _include_routes(app: FastAPI) -> None:
    app.include_router(health_router)
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
    app.get("/languages", tags=["public"], summary="List supported languages")(
        list_supported_languages
    )


GATEWAY_DESCRIPTION = """
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
    """


def create_app() -> FastAPI:
    """Build one gateway app. Its lifespan builds the app's own dependency container."""
    configure_logging()
    app = FastAPI(
        title=f"{DISPLAY_NAME} API Gateway",
        description=GATEWAY_DESCRIPTION,
        version="1.1.0",
        lifespan=lifespan,
    )
    # This app's registry and series; every lifespan of the app reuses them.
    metrics = GatewayMetrics.build()
    app.state.gateway_metrics = metrics
    app.state.prometheus_registry = metrics.registry
    app.state.dependencies = None

    # The last middleware added is the outermost, so adding this one before CORS puts
    # it inside CORS: a crash still answers with CORS headers.
    app.add_middleware(UnhandledErrorMiddleware)
    setup_cors_for_websockets(app)
    app.state.rate_limits = RateLimits()
    app.add_middleware(RateLimitMiddleware, limits=app.state.rate_limits)
    _include_routes(app)
    return app


app = create_app()


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
