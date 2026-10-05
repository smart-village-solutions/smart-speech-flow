"""The ports between a session manager and the realtime side of its app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, Protocol, TypeVar

from .realtime_protocol import Frame
from .session_models import ClientType, Session

if TYPE_CHECKING:
    from .websocket import WebSocketManager

KeyT_contra = TypeVar("KeyT_contra", contravariant=True)


class SessionSockets[KeyT_in](Protocol):
    """What a session manager calls on the realtime side of its app.

    `WebSocketManager` is a `SessionSockets[TenantSessionKey]`. The legacy
    adapter's `SessionSockets[str]` is satisfied only by test doubles now.
    The key is inferred contravariant: it appears only as a parameter.
    """

    async def handle_session_termination(self, session_id: KeyT_in, reason: str) -> None: ...

    async def broadcast_to_session(self, session_id: KeyT_in, message: Frame) -> None: ...


class SessionRegistry(Protocol[KeyT_contra]):
    """What the WebSocket manager needs from a session manager.

    Generic in the key rather than widened to `Any`. The WebSocket manager
    takes a `SessionRegistry[TenantSessionKey]`, which `TenantSessionManager`
    is. `LegacySessionManager` is none: its lookups stayed synchronous.
    """

    def register_websocket_manager(self, manager: WebSocketManager) -> None: ...

    async def get_session(self, session_id: KeyT_contra) -> Optional[Session]: ...

    async def add_websocket_connection(
        self, session_id: KeyT_contra, client_type: ClientType, websocket: Any
    ) -> None: ...

    async def remove_websocket_connection(
        self, session_id: KeyT_contra, client_type: ClientType
    ) -> None: ...
