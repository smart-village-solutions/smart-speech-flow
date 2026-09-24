"""The gateway's composition root.

Each app instance owns one `GatewayDependencies`, built by its lifespan and
kept at `app.state.dependencies`. Route handlers reach a collaborator only
through the provider below, so a test replaces it per app with
`app.dependency_overrides` instead of mutating module state. See "Dependency
ownership" in openspec/changes/refactor-api-gateway-boundaries/design.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from starlette.requests import HTTPConnection

if TYPE_CHECKING:
    from prometheus_client import CollectorRegistry, Counter

    from .audio_storage import AudioStore
    from .auth import OidcKeyCache
    from .circuit_breaker_client import CircuitBreakerServiceClient
    from .conversation_service import ConversationService
    from .pipeline_admission import PipelineAdmission
    from .pipeline_logic import SpeechPipeline
    from .quality_telemetry import QualityTelemetry
    from .realtime_ticket import RealtimeTicketStore
    from .runtime_policy import RuntimePolicyGate
    from .service_health import ServiceHealthManager
    from .session_lifecycle import SessionLifecycleService
    from .session_manager import TenantSessionManager
    from .session_pseudonym import SessionPseudonymizer
    from .studio_login_directory import StudioLoginDirectoryService
    from .studio_runtime_flow import StudioRuntimeFlow
    from .translation_refiner import BaseTranslationRefiner
    from .websocket import WebSocketManager
    from .websocket_fallback import WebSocketFallbackManager
    from .websocket_monitor import WebSocketMonitor
    from .websocket_polling_routes import TenantPollingStore


class GatewayDependenciesUnavailable(RuntimeError):
    """A request reached an app whose lifespan has not built its container."""


@dataclass(slots=True)
class GatewayDependencies:
    """Every request-facing collaborator of one gateway app instance."""

    prometheus_registry: CollectorRegistry
    pseudonymizer: SessionPseudonymizer
    # The directory every audio write, read and deletion of this app uses.
    audio_store: AudioStore
    session_manager: TenantSessionManager
    realtime_tickets: RealtimeTicketStore
    polling_store: TenantPollingStore
    websocket_manager: WebSocketManager
    conversation_service: ConversationService
    session_lifecycle: SessionLifecycleService
    # None when Studio is unconfigured; each consumer maps that to its own
    # fail-closed answer.
    studio_runtime_flow: StudioRuntimeFlow | None
    login_directory: StudioLoginDirectoryService | None
    # The breakers, their health polling and the degradation mode derived
    # from them; the speech pipeline calls through the same breakers.
    service_health: ServiceHealthManager
    circuit_breaker_client: CircuitBreakerServiceClient
    speech_pipeline: SpeechPipeline
    websocket_monitor: WebSocketMonitor
    fallback_manager: WebSocketFallbackManager
    oidc_key_cache: OidcKeyCache
    pipeline_admission: PipelineAdmission | None = None
    quality_telemetry: QualityTelemetry | None = None
    quality_telemetry_exporter: Any = None
    feedback_repository: Any = None
    feedback_maintenance_repository: Any = None
    feedback_read_repository: Any = None
    feedback_service: Any = None
    feedback_read_service: Any = None
    feedback_maintenance: Any = None


def build_gateway_dependencies(
    *,
    prometheus_registry: CollectorRegistry,
    redis: Any = None,
    redis_namespace: str = "ssf",
    studio_runtime_flow: StudioRuntimeFlow | None = None,
    runtime_policy: RuntimePolicyGate | None = None,
    polling_messages_dropped: Counter | None = None,
    translation_refiner: BaseTranslationRefiner,
    pipeline_admission: PipelineAdmission | None = None,
    quality_telemetry: QualityTelemetry | None = None,
    quality_telemetry_exporter: Any = None,
    audio_store: AudioStore | None = None,
) -> GatewayDependencies:
    """Construct one app's collaborators.

    `redis` is the verified connection in production, shared by the session
    store and the realtime tickets; without one both live in process memory,
    as local development always has. `studio_runtime_flow` and the persistence
    gate built on it come from the lifespan; None means Studio is unconfigured,
    and a None gate refuses every write of conversation content. The refiner,
    the admission gate and quality telemetry come from the lifespan too, which
    builds them first; None leaves the pipeline unbounded and emits no rows.
    Without an `audio_store` the app stores audio under SSF_AUDIO_BASE_DIR as
    it is set when this runs.
    """
    # Imported here: every module below imports its provider from this one.
    from .audio_processing import WavAudioValidator
    from .audio_storage import AudioStore
    from .auth import _key_cache
    from .circuit_breaker_client import CircuitBreakerServiceClient
    from .conversation_service import ConversationService
    from .pipeline_logic import SpeechPipeline
    from .realtime_ticket import (
        MemoryRealtimeTicketBackend,
        RealtimeTicketStore,
        RedisRealtimeTicketBackend,
    )
    from .service_health import ServiceHealthManager
    from .session_lifecycle import SessionLifecycleService
    from .session_manager import TenantSessionManager
    from .session_store import MemoryTenantSessionStore, RedisTenantSessionStore
    from .speech_services import HttpSpeechServices
    from .studio_login_directory import login_directory_from_environment
    from .websocket import WebSocketManager
    from .websocket_fallback import fallback_manager
    from .websocket_monitor import get_websocket_monitor
    from .websocket_polling_routes import TenantPollingStore

    realtime_tickets = RealtimeTicketStore(
        RedisRealtimeTicketBackend(redis) if redis is not None else MemoryRealtimeTicketBackend(),
        namespace=redis_namespace,
    )
    polling_store = TenantPollingStore(messages_dropped=polling_messages_dropped)
    audio_store = audio_store if audio_store is not None else AudioStore.from_environment()
    websocket_monitor = get_websocket_monitor()
    # The monitor's, while it is a process-wide adapter: with no configured key
    # every pseudonymizer draws its own, and the two would stop correlating.
    pseudonymizer = websocket_monitor.pseudonymizer
    session_manager = TenantSessionManager(
        store=(
            RedisTenantSessionStore(redis, namespace=redis_namespace)
            if redis is not None
            else MemoryTenantSessionStore()
        ),
        audio_store=audio_store,
        realtime_tickets=realtime_tickets,
        polling_store=polling_store,
        runtime_policy=runtime_policy,
        pseudonymizer=pseudonymizer,
    )
    websocket_manager = WebSocketManager(session_manager, polling_store)
    service_health = ServiceHealthManager()
    speech_pipeline = SpeechPipeline(
        speech=HttpSpeechServices(service_health.circuit_breakers),
        refiner=translation_refiner,
        validator=WavAudioValidator(),
    )
    return GatewayDependencies(
        prometheus_registry=prometheus_registry,
        pseudonymizer=pseudonymizer,
        audio_store=audio_store,
        session_manager=session_manager,
        realtime_tickets=realtime_tickets,
        polling_store=polling_store,
        websocket_manager=websocket_manager,
        conversation_service=ConversationService(
            session_manager,
            pipeline=speech_pipeline,
            audio_store=audio_store,
            admission=pipeline_admission,
            quality_telemetry=quality_telemetry,
            websocket_manager=websocket_manager,
        ),
        session_lifecycle=SessionLifecycleService(session_manager),
        studio_runtime_flow=studio_runtime_flow,
        login_directory=login_directory_from_environment(),
        service_health=service_health,
        circuit_breaker_client=CircuitBreakerServiceClient(service_health),
        speech_pipeline=speech_pipeline,
        websocket_monitor=websocket_monitor,
        fallback_manager=fallback_manager,
        oidc_key_cache=_key_cache,
        pipeline_admission=pipeline_admission,
        quality_telemetry=quality_telemetry,
        quality_telemetry_exporter=quality_telemetry_exporter,
    )


def _container(connection: HTTPConnection) -> GatewayDependencies:
    container = getattr(connection.app.state, "dependencies", None)
    if not isinstance(container, GatewayDependencies):
        raise GatewayDependenciesUnavailable("gateway dependencies are not built")
    return container


def optional_container(connection: Any) -> GatewayDependencies | None:
    """The container, or None for a mock request or an app before its lifespan."""
    app = getattr(connection, "app", None)
    container = getattr(getattr(app, "state", None), "dependencies", None)
    return container if isinstance(container, GatewayDependencies) else None


def get_session_manager(connection: HTTPConnection) -> TenantSessionManager:
    return _container(connection).session_manager


def get_realtime_ticket_store(connection: HTTPConnection) -> RealtimeTicketStore:
    return _container(connection).realtime_tickets


def get_polling_store(connection: HTTPConnection) -> TenantPollingStore:
    return _container(connection).polling_store


def get_websocket_manager(connection: HTTPConnection) -> WebSocketManager:
    return _container(connection).websocket_manager


def get_conversation_service(connection: HTTPConnection) -> ConversationService:
    return _container(connection).conversation_service


def get_session_lifecycle(connection: HTTPConnection) -> SessionLifecycleService:
    return _container(connection).session_lifecycle


def get_studio_runtime_flow(connection: HTTPConnection) -> StudioRuntimeFlow | None:
    return _container(connection).studio_runtime_flow


def get_login_directory(connection: HTTPConnection) -> StudioLoginDirectoryService | None:
    return _container(connection).login_directory


def get_circuit_breaker_client(connection: HTTPConnection) -> CircuitBreakerServiceClient:
    return _container(connection).circuit_breaker_client


def get_speech_pipeline(connection: HTTPConnection) -> SpeechPipeline:
    return _container(connection).speech_pipeline


def get_pipeline_admission(connection: HTTPConnection) -> PipelineAdmission | None:
    return _container(connection).pipeline_admission


def get_connection_monitor(connection: HTTPConnection) -> WebSocketMonitor:
    return _container(connection).websocket_monitor


def get_prometheus_registry(connection: HTTPConnection) -> CollectorRegistry:
    return _container(connection).prometheus_registry


def get_oidc_key_cache(connection: HTTPConnection) -> OidcKeyCache:
    return _container(connection).oidc_key_cache


def get_quality_telemetry(connection: HTTPConnection) -> QualityTelemetry | None:
    return _container(connection).quality_telemetry
