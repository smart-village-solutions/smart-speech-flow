"""
WebSocket Polling Fallback API Routes
Provides REST endpoints for clients that cannot establish WebSocket connections
due to CORS, network, or compatibility issues.
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .session_manager import ClientType, session_manager
from .websocket_fallback import FallbackReason, fallback_manager

router = APIRouter(prefix="/api/websocket/polling", tags=["WebSocket Polling Fallback"])


class PollingMessage(BaseModel):
    """Message sent via polling"""

    type: str
    content: Dict[str, Any]
    session_id: str
    client_type: str
    timestamp: Optional[str] = None


class FallbackActivationRequest(BaseModel):
    """Request to activate polling fallback"""

    session_id: str
    client_type: str
    origin: Optional[str] = None
    reason: str = "manual_fallback"
    error_details: Optional[Dict[str, Any]] = None


@router.post("/activate")
async def activate_polling_fallback(
    request: FallbackActivationRequest, client_request: Request
):
    """
    Manually activate polling fallback for a client
    This endpoint is called when WebSocket connection fails on the client side
    """
    try:
        # Validate session exists
        session_status = session_manager.get_session_status(request.session_id)
        if not session_status or session_status.value not in [
            "active",
            "inactive",
            "pending",
        ]:
            raise HTTPException(
                status_code=404,
                detail=f"Session {request.session_id} not found or inactive",
            )

        # Validate client type
        try:
            ClientType(request.client_type)
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"Invalid client type: {request.client_type}"
            )

        # Map reason to FallbackReason enum
        try:
            fallback_reason = FallbackReason(request.reason)
        except ValueError:
            fallback_reason = FallbackReason.MANUAL_FALLBACK

        # Get origin from request headers if not provided
        origin = request.origin or client_request.headers.get("origin")

        # Activate polling fallback
        polling_id = await fallback_manager.activate_polling_fallback(
            session_id=request.session_id,
            client_type=request.client_type,
            origin=origin,
            reason=fallback_reason,
        )

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "polling_id": polling_id,
                "fallback_reason": fallback_reason.value,
                "endpoints": {
                    "poll": f"/api/websocket/polling/poll/{polling_id}",
                    "send": f"/api/websocket/polling/send/{polling_id}",
                    "status": f"/api/websocket/polling/status/{polling_id}",
                    "recover": f"/api/websocket/polling/recover/{polling_id}",
                },
                "config": {
                    "polling_interval": 5,
                    "recovery_check_interval": 300,
                    "max_message_queue_size": 100,
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to activate polling fallback: {str(e)}"
        )


@router.get("/poll/{polling_id}")
async def poll_messages(
    polling_id: str,
    timeout: int = Query(
        default=30, ge=1, le=60, description="Long polling timeout in seconds"
    ),
):
    """
    Long polling endpoint to retrieve queued messages
    """
    try:
        # Check if polling client exists
        client_status = await fallback_manager.get_polling_client_status(polling_id)
        if not client_status:
            raise HTTPException(
                status_code=404,
                detail=f"Polling client {polling_id} not found or expired",
            )

        # Get immediate messages
        messages = await fallback_manager.poll_messages(polling_id)

        # If no messages, wait for new ones (long polling)
        if not messages and timeout > 0:
            # Simple long polling implementation
            await asyncio.sleep(1)  # Brief wait for potential new messages
            messages = await fallback_manager.poll_messages(polling_id)

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "polling_id": polling_id,
                "messages": messages,
                "message_count": len(messages),
                "has_more": False,  # TODO(Issue #XX): Implement pagination for large message queues
                "next_poll_interval": client_status["polling_interval"],
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to poll messages: {str(e)}"
        )


@router.post("/send/{polling_id}")
async def send_message_via_polling(polling_id: str, message: PollingMessage):
    """
    Send message from polling client to session
    """
    try:
        # Validate polling client exists
        client_status = await fallback_manager.get_polling_client_status(polling_id)
        if not client_status:
            raise HTTPException(
                status_code=404, detail=f"Polling client {polling_id} not found"
            )

        # Validate session matches
        if message.session_id != client_status["session_id"]:
            raise HTTPException(status_code=400, detail="Session ID mismatch")

        # Prepare message for session broadcast
        broadcast_message = {
            "type": message.type,
            "session_id": message.session_id,
            "client_type": message.client_type,
            "sender_id": polling_id,
            "content": message.content,
            "timestamp": message.timestamp or datetime.utcnow().isoformat(),
            "via_polling": True,
        }

        # Broadcast to session via WebSocket manager
        from .websocket import websocket_manager

        await websocket_manager.broadcast_to_session(
            session_id=message.session_id,
            message=broadcast_message,
            exclude_connection=None,  # Don't exclude polling client
        )

        # Also queue message for other polling clients in the session
        session_fallback_status = await fallback_manager.get_session_fallback_status(
            message.session_id
        )
        for client_info in session_fallback_status["polling_clients"]:
            if client_info["polling_id"] != polling_id:  # Don't send to sender
                await fallback_manager.send_message_to_polling_client(
                    polling_id=client_info["polling_id"], message=broadcast_message
                )

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": "Message sent successfully",
                "broadcast_count": 1,  # TODO(Issue #XX): Track actual broadcast count from fallback_manager
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send message: {str(e)}")


@router.get("/status/{polling_id}")
async def get_polling_status(polling_id: str):
    """
    Get status and information about a polling client
    """
    try:
        client_status = await fallback_manager.get_polling_client_status(polling_id)
        if not client_status:
            raise HTTPException(
                status_code=404, detail=f"Polling client {polling_id} not found"
            )

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "data": client_status,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get polling status: {str(e)}"
        )


@router.post("/recover/{polling_id}")
async def attempt_websocket_recovery(polling_id: str):
    """
    Attempt to recover WebSocket connection for polling client
    """
    try:
        recovery_result = await fallback_manager.attempt_websocket_recovery(polling_id)

        if not recovery_result["success"]:
            raise HTTPException(
                status_code=400,
                detail=recovery_result.get("error", "Recovery attempt failed"),
            )

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": "WebSocket recovery attempt initiated",
                "recovery_info": recovery_result["recovery_info"],
                "instructions": {
                    "action": "retry_websocket_connection",
                    "websocket_url": f"/ws/{recovery_result['recovery_info']['session_id']}/{recovery_result['recovery_info']['client_type']}",
                    "fallback_on_failure": True,
                    "retry_delay": 5,
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to attempt recovery: {str(e)}"
        )


@router.post("/recover/{polling_id}/success")
async def websocket_recovery_success(polling_id: str):
    """
    Notify that WebSocket recovery was successful
    """
    try:
        await fallback_manager.websocket_recovery_successful(polling_id)

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": "WebSocket recovery completed successfully",
                "polling_client_deactivated": True,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to complete recovery: {str(e)}"
        )


@router.post("/recover/{polling_id}/failed")
async def websocket_recovery_failed(
    polling_id: str, failure_reason: str = Query(default="websocket_connection_failed")
):
    """
    Notify that WebSocket recovery attempt failed
    """
    try:
        # Map failure reason
        try:
            fallback_reason = FallbackReason(failure_reason)
        except ValueError:
            fallback_reason = FallbackReason.WEBSOCKET_CONNECTION_FAILED

        await fallback_manager.websocket_recovery_failed(polling_id, fallback_reason)

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": "WebSocket recovery failure recorded",
                "continues_polling": True,
                "next_retry_scheduled": True,  # TODO(Issue #XX): Return actual retry schedule from fallback_manager
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to record recovery failure: {str(e)}"
        )


@router.delete("/deactivate/{polling_id}")
async def deactivate_polling_fallback(polling_id: str):
    """
    Deactivate polling fallback for a client
    """
    try:
        success = await fallback_manager.deactivate_polling_fallback(polling_id)

        if not success:
            raise HTTPException(
                status_code=404, detail=f"Polling client {polling_id} not found"
            )

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": "Polling fallback deactivated successfully",
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to deactivate polling fallback: {str(e)}"
        )


@router.get("/session/{session_id}/fallback-status")
async def get_session_fallback_status(session_id: str):
    """
    Get fallback status for all clients in a session
    """
    try:
        fallback_status = await fallback_manager.get_session_fallback_status(session_id)

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "data": fallback_status,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get session fallback status: {str(e)}"
        )


@router.get("/statistics")
async def get_fallback_statistics():
    """
    Get comprehensive fallback system statistics
    """
    try:
        stats = fallback_manager.get_fallback_statistics()

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "data": stats,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get fallback statistics: {str(e)}"
        )
