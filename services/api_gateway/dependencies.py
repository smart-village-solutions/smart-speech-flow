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

    from .auth import OidcKeyCache
    from .circuit_breaker_client import CircuitBreakerServiceClient
    from .conversation_service import ConversationService
    from .pipeline_admission import PipelineAdmission
    from .quality_telemetry import QualityTelemetry
    from .realtime_ticket import RealtimeTicketStore
    from .session_manager import SessionManager
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
    session_manager: SessionManager
    realtime_tickets: RealtimeTicketStore
    polling_store: TenantPollingStore
    websocket_manager: WebSocketManager
    conversation_service: ConversationService
    # None when Studio is unconfigured; each consumer maps that to its own
    # fail-closed answer.
    studio_runtime_flow: StudioRuntimeFlow | None
    login_directory: StudioLoginDirectoryService | None
    circuit_breaker_client: CircuitBreakerServiceClient
    websocket_monitor: WebSocketMonitor
    fallback_manager: WebSocketFallbackManager
    translation_refiner: BaseTranslationRefiner
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
    ticket_backend: Any = None,
    ticket_namespace: str = "ssf",
    studio_runtime_flow: StudioRuntimeFlow | None = None,
    polling_messages_dropped: Counter | None = None,
) -> GatewayDependencies:
    """Construct one app's collaborators.

    `ticket_backend` is the verified Redis client in production; without one
    the tickets live in process memory, as local development always has.
    `studio_runtime_flow` comes from the lifespan, which builds it earlier to
    bind the persistence gate; None means Studio is unconfigured.
    """
    # Imported here: every module below imports its provider from this one.
    from .auth import _key_cache
    from .circuit_breaker_client import circuit_breaker_client
    from .conversation_service import ConversationService
    from .realtime_ticket import MemoryRealtimeTicketBackend, RealtimeTicketStore
    from .session_manager import session_manager
    from .studio_login_directory import login_directory_from_environment
    from .translation_refiner import translation_refiner
    from .websocket import WebSocketManager
    from .websocket_fallback import fallback_manager
    from .websocket_monitor import get_websocket_monitor
    from .websocket_polling_routes import TenantPollingStore

    realtime_tickets = RealtimeTicketStore(
        ticket_backend if ticket_backend is not None else MemoryRealtimeTicketBackend(),
        namespace=ticket_namespace,
    )
    polling_store = TenantPollingStore(messages_dropped=polling_messages_dropped)
    session_manager.attach_realtime(realtime_tickets, polling_store)
    return GatewayDependencies(
        prometheus_registry=prometheus_registry,
        session_manager=session_manager,
        realtime_tickets=realtime_tickets,
        polling_store=polling_store,
        websocket_manager=WebSocketManager(session_manager, polling_store),
        conversation_service=ConversationService(session_manager),
        studio_runtime_flow=studio_runtime_flow,
        login_directory=login_directory_from_environment(),
        circuit_breaker_client=circuit_breaker_client,
        websocket_monitor=get_websocket_monitor(),
        fallback_manager=fallback_manager,
        translation_refiner=translation_refiner,
        oidc_key_cache=_key_cache,
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


def get_session_manager(connection: HTTPConnection) -> SessionManager:
    return _container(connection).session_manager


def get_realtime_ticket_store(connection: HTTPConnection) -> RealtimeTicketStore:
    return _container(connection).realtime_tickets


def get_polling_store(connection: HTTPConnection) -> TenantPollingStore:
    return _container(connection).polling_store


def get_websocket_manager(connection: HTTPConnection) -> WebSocketManager:
    return _container(connection).websocket_manager


def get_conversation_service(connection: HTTPConnection) -> ConversationService:
    return _container(connection).conversation_service


def get_studio_runtime_flow(connection: HTTPConnection) -> StudioRuntimeFlow | None:
    return _container(connection).studio_runtime_flow


def get_login_directory(connection: HTTPConnection) -> StudioLoginDirectoryService | None:
    return _container(connection).login_directory


def get_circuit_breaker_client(connection: HTTPConnection) -> CircuitBreakerServiceClient:
    return _container(connection).circuit_breaker_client


def get_connection_monitor(connection: HTTPConnection) -> WebSocketMonitor:
    return _container(connection).websocket_monitor


def get_prometheus_registry(connection: HTTPConnection) -> CollectorRegistry:
    return _container(connection).prometheus_registry


def get_oidc_key_cache(connection: HTTPConnection) -> OidcKeyCache:
    return _container(connection).oidc_key_cache


def get_quality_telemetry(connection: HTTPConnection) -> QualityTelemetry | None:
    return _container(connection).quality_telemetry
