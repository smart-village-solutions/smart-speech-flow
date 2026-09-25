"""
WebSocket Monitoring API Routes
Provides comprehensive monitoring and health check endpoints for WebSocket infrastructure.
"""

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from .dependencies import get_connection_monitor
from .websocket_monitor import WebSocketMonitor

router = APIRouter(prefix="/api/websocket/monitoring", tags=["WebSocket Monitoring"])


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


@router.get("/health")
def websocket_health_check(
    monitor: Annotated[WebSocketMonitor, Depends(get_connection_monitor)],
):
    """
    WebSocket system health check endpoint
    Returns current health status and key metrics
    """
    try:
        health_status = monitor.get_health_status()

        return JSONResponse(
            status_code=200 if health_status["status"] == "healthy" else 503,
            content={
                "status": "success",
                "data": health_status,
                "timestamp": utc_now_iso(),
            },
        )
    except Exception:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": "Health check failed",
                "timestamp": utc_now_iso(),
            },
        )
