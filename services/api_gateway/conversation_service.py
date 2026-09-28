"""Trusted, tenant-scoped entry point for conversation message processing.

Routes reach message processing only through this service, and the service
imports nothing from routes/: the dependency points from transport to
application, never back (#347 §2).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request, Response
from fastapi.responses import FileResponse

from .audio_storage import AudioVariant, audio_path, scope_pipeline_audio_urls, scoped_audio_url
from .message_processing import process_audio_input, process_text_input, send_unified_message
from .session_manager import ClientType, SessionStatus, TenantSessionManager
from .tenant_session import TenantSessionKey

if TYPE_CHECKING:
    from .message_models import MessageResponse
    from .websocket import WebSocketManager


class ConversationService:
    """Apply the server-assigned role before entering the shared pipeline.

    `build_gateway_dependencies` hands it the app's session manager and
    WebSocket manager. Without a WebSocket manager a processed message reaches
    no live connection, which is what unit tests that build one directly want.
    """

    def __init__(
        self,
        sessions: TenantSessionManager,
        *,
        websocket_manager: WebSocketManager | None = None,
    ) -> None:
        self._sessions = sessions
        self._websocket_manager = websocket_manager

    async def process(
        self, key: TenantSessionKey, sender: ClientType, request: Request
    ) -> MessageResponse:
        return await send_unified_message(
            key, sender, request, self._websocket_manager, sessions=self._sessions
        )

    async def process_text(
        self, key: TenantSessionKey, sender: ClientType, request: Request
    ) -> MessageResponse:
        return await process_text_input(
            key,
            sender,
            request,
            time.perf_counter(),
            self._websocket_manager,
            sessions=self._sessions,
        )

    async def process_audio(
        self, key: TenantSessionKey, sender: ClientType, request: Request
    ) -> MessageResponse:
        return await process_audio_input(
            key,
            sender,
            request,
            time.perf_counter(),
            self._websocket_manager,
            sessions=self._sessions,
        )

    def messages(self, key: TenantSessionKey, role: ClientType) -> list[dict[str, object]]:
        session = self._sessions.get_session(key)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        # Availability comes from the markers the writer recorded; settlement clears them
        # when it removes audio. `audio()` alone checks the disk, as it serves the file.
        result: list[dict[str, object]] = []
        for message in session.messages:
            item = message.to_dict()
            if message.translated_audio_available:
                item["audio_url"] = scoped_audio_url(
                    key, role.value, message.id, AudioVariant.TRANSLATED
                )
            pipeline_input = (
                message.pipeline_metadata.get("input")
                if isinstance(message.pipeline_metadata, dict)
                else None
            )
            has_original_audio = bool(message.original_audio_url) or (
                isinstance(pipeline_input, dict) and pipeline_input.get("type") == "audio"
            )
            if has_original_audio:
                item["original_audio_url"] = scoped_audio_url(
                    key, role.value, message.id, AudioVariant.ORIGINAL
                )
            scoped_metadata = scope_pipeline_audio_urls(
                message.pipeline_metadata, key, role.value, message.id
            )
            if scoped_metadata is not None:
                item["pipeline_metadata"] = scoped_metadata
            result.append(item)
        return result

    def audio(
        self,
        key: TenantSessionKey,
        message_id: str,
        variant: AudioVariant,
    ) -> Response:
        session = self._sessions.get_session(key)
        if session is None or session.status is SessionStatus.TERMINATED:
            raise HTTPException(status_code=404, detail="Session not found")
        message = next(
            (candidate for candidate in session.messages if candidate.id == message_id),
            None,
        )
        if message is None:
            raise HTTPException(status_code=404, detail="Audio file not found")
        path = audio_path(key, message_id, variant)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Audio file not found")
        return FileResponse(path, media_type="audio/wav")
