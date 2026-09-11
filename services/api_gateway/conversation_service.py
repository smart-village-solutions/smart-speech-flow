"""Trusted, tenant-scoped entry point for conversation message processing."""

from __future__ import annotations

import base64
import time
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request, Response
from fastapi.responses import FileResponse

from .audio_storage import (
    AudioVariant,
    audio_path,
    scope_pipeline_audio_urls,
    scoped_audio_url,
)
from .session_manager import ClientType, SessionStatus, session_manager
from .tenant_session import TenantSessionKey

if TYPE_CHECKING:
    from .routes.session import MessageResponse
    from .websocket import WebSocketManager


class ConversationService:
    """Apply the server-assigned role before entering the shared pipeline."""

    async def process(
        self,
        key: TenantSessionKey,
        sender: ClientType,
        request: Request,
        manager: WebSocketManager | None = None,
    ) -> MessageResponse:
        from .routes.session import send_unified_message

        return await send_unified_message(key, sender, request, manager)

    async def process_text(
        self,
        key: TenantSessionKey,
        sender: ClientType,
        request: Request,
        manager: WebSocketManager | None = None,
    ) -> MessageResponse:
        from .routes.session import process_text_input

        return await process_text_input(
            key, sender, request, time.perf_counter(), manager
        )

    async def process_audio(
        self,
        key: TenantSessionKey,
        sender: ClientType,
        request: Request,
        manager: WebSocketManager | None = None,
    ) -> MessageResponse:
        from .routes.session import process_audio_input

        return await process_audio_input(
            key, sender, request, time.perf_counter(), manager
        )

    def messages(
        self, key: TenantSessionKey, role: ClientType
    ) -> list[dict[str, object]]:
        session = session_manager.get_session(key)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        result: list[dict[str, object]] = []
        for message in session.messages:
            item = message.to_dict()
            if message.audio_base64:
                item["audio_url"] = scoped_audio_url(
                    key, role.value, message.id, AudioVariant.TRANSLATED
                )
            pipeline_input = (
                message.pipeline_metadata.get("input")
                if isinstance(message.pipeline_metadata, dict)
                else None
            )
            has_original_audio = bool(message.original_audio_url) or (
                isinstance(pipeline_input, dict)
                and pipeline_input.get("type") == "audio"
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
        session = session_manager.get_session(key)
        if session is None or session.status is SessionStatus.TERMINATED:
            raise HTTPException(status_code=404, detail="Session not found")
        message = next(
            (candidate for candidate in session.messages if candidate.id == message_id),
            None,
        )
        if message is None:
            raise HTTPException(status_code=404, detail="Audio file not found")
        if variant is AudioVariant.TRANSLATED and message.audio_base64:
            return Response(
                content=base64.b64decode(message.audio_base64),
                media_type="audio/wav",
            )
        path = audio_path(key, message_id, variant)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Audio file not found")
        return FileResponse(path, media_type="audio/wav")


conversation_service = ConversationService()
