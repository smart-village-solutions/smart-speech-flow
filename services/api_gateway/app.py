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

from .client_origin import configured_client_origin
from .dependencies import GatewayDependencies, build_gateway_dependencies
from .gateway_metrics import GatewayMetrics
from .pipeline_admission import PipelineAdmission, PipelineAdmissionConfig, PipelineAdmissionMetrics
from .rate_limiter import RateLimitMiddleware, RateLimits
from .refinement_metrics import RefinementMetrics

if TYPE_CHECKING:
    from .audio_storage import AudioStore
    from .quality_telemetry import QualityTelemetry, TelemetryMode
    from .runtime_policy import RuntimePolicyGate
    from .studio_runtime_flow import StudioRuntimeFlow
    from .tenant_persistence import TenantPersistenceBinding
    from .translation_refiner import BaseTranslationRefiner

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
async def session_timeout_monitor(session_manager: Any) -> None:
    """Background Task für Session-Timeout-Management"""
    while True:
        try:
            await session_manager.check_session_timeouts()
            await asyncio.sleep(60)  # Alle 60 Sekunden prüfen
        except Exception as e:
            print(f"⚠️ Fehler im Session-Timeout-Monitor: {e}")
            await asyncio.sleep(60)


async def websocket_monitor_task(monitor: Any, manager: Any) -> None:
    """Background Task für WebSocket-Monitoring und Cleanup"""
    await asyncio.sleep(1)  # Kurz warten bis Startup abgeschlossen

    try:
        print("🚀 WebSocket-Monitoring gestartet")
        await monitor.periodic_cleanup(lambda: manager.all_connections.keys())
    except Exception as e:
        print(f"⚠️ Fehler im WebSocket-Monitor: {e}")


async def circuit_breaker_monitor(circuit_breaker_client: Any) -> None:
    """Starts the service health polling for the lifespan.

    The cleanup loop that used to live here swept an expired-response cache
    and a request queue, both of which went with the fallback machinery in
    #219. ServiceHealthManager owns its own polling task, so there is nothing
    left for this one to do after starting it.
    """
    try:
        await circuit_breaker_client.start_health_monitoring()
        print("🚀 Circuit Breaker Health Monitoring gestartet")
    except Exception as e:
        print(f"❌ Circuit Breaker Monitor Startup Fehler: {e}")


async def audio_cleanup_task(session_manager: Any, audio_store: "AudioStore") -> None:
    """Background Task für automatisches Löschen alter Inhalte (Retention)"""
    from .session_manager import utc_now

    try:
        print("🧹 Audio-Cleanup-Service gestartet (läuft stündlich)")

        while True:
            try:
                # Stündliche Cleanup-Routine
                await asyncio.sleep(3600)  # 1 Stunde warten

                # Cleanup durchführen
                stats = audio_store.cleanup_expired()
                print(f"🧹 Audio-Cleanup abgeschlossen: {stats['total_deleted']} Dateien gelöscht")

                # Transcripts expire on the same pass. Audio alone would keep
                # the weaker half of the promise.
                content = session_manager.sweep_expired_content(utc_now())
                print(
                    "🧹 Content-Sweep abgeschlossen: "
                    f"{content['refused_removed']} abgelehnt, "
                    f"{content['expired_removed']} abgelaufen"
                )

                # Disk Usage loggen
                disk_stats = audio_store.disk_usage()
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


async def _connect_feedback_request_path(state: Any, dsn: str, sessions: Any) -> bool:
    """Wire POST /api/feedback. Returns False only when retrying could help."""
    if state.feedback_service is not None:
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
        from .feedback.tenant import ConfiguredTenantResolver, SessionTenantResolver
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
    except Exception as error:
        # Type name only: a connection error can carry the DSN, and the DSN
        # carries the database password.
        sys.stderr.write(
            f"Feedback persistence unavailable ({type(error).__name__}); "
            "POST /api/feedback will answer 503 until it connects\n"
        )
        return False

    state.feedback_repository = repository
    state.feedback_service = FeedbackService(
        repository=repository,
        cipher=cipher,
        # The session's own tenant; the configured one only for a legacy
        # session or a submission that names no session.
        tenant_resolver=SessionTenantResolver(
            fallback=ConfiguredTenantResolver.from_environment(),
        ),
        session_manager=sessions,
        telemetry=state.quality_telemetry,
        pseudonymizer=state.pseudonymizer,
    )
    sys.stderr.write("Feedback persistence ready\n")
    return True


async def _connect_feedback_read_path(state: Any, dsn: str) -> bool:
    """Wire the authorised Studio read endpoints. Returns False to retry.

    A third role and a third pool, because the read path's privileges are
    deliberately not the union of the other two: it may SELECT and write an
    access audit row, and it may not write or delete feedback. See migration
    003, which explains why neither existing role can serve these reads.

    An unset DSN is a supported deployment, not a fault: a site that never
    granted Studio read access keeps collecting feedback, and the read
    endpoints answer 503.
    """
    if not dsn:
        sys.stderr.write(
            "Feedback reading disabled: SSF_FEEDBACK_READER_DATABASE_URL is not set; "
            "the Studio feedback endpoints will answer 503\n"
        )
        return True

    if getattr(state, "feedback_read_service", None) is not None:
        return True

    # Its own import guard, for the reason _connect_feedback_request_path
    # documents: crypto.py's dependency arrives as an extra, and an ImportError
    # escaping here would stop the gateway booting.
    try:
        from .feedback.crypto import FeedbackCipher, MissingEncryptionKey
        from .feedback.read import FeedbackReadService
        from .feedback.repository import PostgresFeedbackReadRepository
    except ImportError as error:
        sys.stderr.write(
            f"Feedback reading disabled: {type(error).__name__}; "
            "the Studio feedback endpoints will answer 503\n"
        )
        return True

    try:
        cipher = FeedbackCipher.from_environment()
    except MissingEncryptionKey:
        sys.stderr.write(
            "Feedback reading disabled: SSF_FEEDBACK_ENCRYPTION_KEY is missing or "
            "malformed; the Studio feedback endpoints will answer 503\n"
        )
        return True

    try:
        repository = await PostgresFeedbackReadRepository.create(
            dsn=dsn,
            password=_feedback_password("SSF_FEEDBACK_READER_DATABASE_PASSWORD"),
        )
    except Exception as error:
        # Type name only: a connection error can carry the DSN, and the DSN
        # carries the database password.
        sys.stderr.write(
            f"Feedback reading unavailable ({type(error).__name__}); the Studio "
            "feedback endpoints will answer 503 until it connects\n"
        )
        return False

    state.feedback_read_repository = repository
    state.feedback_read_service = FeedbackReadService(repository=repository, cipher=cipher)
    sys.stderr.write("Feedback reading ready\n")
    return True


async def _connect_feedback_maintenance(state: Any, dsn: str) -> bool:
    """Wire the recovery and retention passes, reporting on their own.

    Separate from the request path in both directions: collecting feedback
    matters more than reconciling it, and a maintenance pool that never opens
    must not be announced as an endpoint outage.
    """
    if state.feedback_maintenance is not None:
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
    except Exception as error:
        sys.stderr.write(
            f"Feedback maintenance unavailable ({type(error).__name__}); "
            "analytics recovery and retention are not running. "
            "POST /api/feedback is unaffected\n"
        )
        return False

    state.feedback_maintenance_repository = repository
    state.feedback_maintenance = FeedbackMaintenance(
        repository=repository,
        telemetry=state.quality_telemetry,
        metrics=FeedbackMaintenanceMetrics(state.prometheus_registry),
        pseudonymizer=state.pseudonymizer,
    )
    sys.stderr.write("Feedback maintenance ready\n")
    return True


async def _wire_feedback(
    state: Any,
    request_dsn: str,
    maintenance_dsn: str,
    sessions: Any,
    read_dsn: str = "",
) -> bool:
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
        connected = await _connect_feedback_request_path(state, request_dsn, sessions)

    maintained = await _connect_feedback_maintenance(state, maintenance_dsn)
    readable = await _connect_feedback_read_path(state, read_dsn)
    sys.stderr.flush()
    return connected and maintained and readable


async def feedback_connect_task(
    state: Any,
    request_dsn: str,
    maintenance_dsn: str,
    sessions: Any,
    read_dsn: str = "",
) -> None:
    """Keep retrying whichever half did not connect at startup.

    The gateway deliberately does not wait for a healthy feedback database --
    a failed migration must not cost every customer their session -- so on a
    first deploy the database is usually still running its init scripts when
    this process starts. Nothing else retries, so without this that ordinary
    race leaves POST /api/feedback answering 503 until someone restarts the
    container.
    """
    if not request_dsn and not maintenance_dsn and not read_dsn:
        return

    delay = FEEDBACK_CONNECT_RETRY_SECONDS
    while True:
        try:
            await asyncio.sleep(delay)
            delay = min(delay * 2, FEEDBACK_CONNECT_RETRY_CEILING_SECONDS)

            if await _wire_feedback(state, request_dsn, maintenance_dsn, sessions, read_dsn):
                return
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f"\u26a0\ufe0f Feedback connection attempt failed: {type(error).__name__}")


async def feedback_maintenance_task(state: Any) -> None:
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

            maintenance = getattr(state, "feedback_maintenance", None)
            if maintenance is None:
                continue

            await maintenance.reconcile_once()

            if elapsed >= FEEDBACK_RETENTION_INTERVAL_SECONDS:
                elapsed = 0
                await maintenance.expire_once()
        except asyncio.CancelledError:
            raise
        except Exception as error:
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
    """What the container hands the conversation service and the pipeline routes.

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


def _feedback_dsns() -> tuple[str, str, str]:
    """The submission, maintenance and Studio-read DSNs, in that order."""
    feedback_dsn = os.environ.get("SSF_FEEDBACK_DATABASE_URL", "").strip()
    # Reconciliation and retention are deployment-wide, so they connect as a
    # role the tenant policy does not filter -- see deploy/postgres/migrations/
    # 002_feedback_roles.sql. Sharing the request pool would leave both passes
    # seeing no rows and reporting success.
    maintenance_dsn = os.environ.get("SSF_FEEDBACK_MAINTENANCE_DATABASE_URL", "").strip()
    # A third role again, for the opposite reason: the Studio read endpoints
    # must stay inside the tenant policy while gaining the audit privileges the
    # submit path deliberately lacks. See 003_feedback_reader.sql.
    read_dsn = os.environ.get("SSF_FEEDBACK_READER_DATABASE_URL", "").strip()
    return feedback_dsn, maintenance_dsn, read_dsn


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


async def _close_feedback(dependencies: GatewayDependencies) -> None:
    pools_at_exit = (
        dependencies.feedback_repository,
        dependencies.feedback_maintenance_repository,
        dependencies.feedback_read_repository,
    )
    dependencies.feedback_repository = None
    dependencies.feedback_maintenance_repository = None
    dependencies.feedback_read_repository = None
    dependencies.feedback_service = None
    dependencies.feedback_read_service = None
    dependencies.feedback_maintenance = None
    for pool_at_exit in pools_at_exit:
        if pool_at_exit is not None:
            await pool_at_exit.close()


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
from .routes.index import router as index_router
from .routes.metrics import metrics
from .routes.pipeline import router as pipeline_router
from .routes.upload import router as upload_router


async def list_supported_languages() -> Any:
    """Expose supported languages without the /api prefix for the public site."""
    return await session.get_supported_languages()


def _include_routes(app: FastAPI) -> None:
    app.include_router(health_router)
    app.include_router(index_router)
    app.include_router(pipeline_router)
    app.include_router(upload_router)
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
    app = FastAPI(
        title="Smart Speech Flow API Gateway",
        description=GATEWAY_DESCRIPTION,
        version="1.1.0",
        lifespan=lifespan,
    )
    # This app's registry and series; every lifespan of the app reuses them.
    metrics = GatewayMetrics.build()
    app.state.gateway_metrics = metrics
    app.state.prometheus_registry = metrics.registry
    setattr(app, "requests_total", metrics.requests_total)
    app.state.dependencies = None

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
