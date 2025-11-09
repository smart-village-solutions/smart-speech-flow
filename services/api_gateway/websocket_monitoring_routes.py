"""
WebSocket Monitoring API Routes
Provides comprehensive monitoring and health check endpoints for WebSocket infrastructure.
"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from .websocket_monitor import get_websocket_monitor

router = APIRouter(prefix="/api/websocket/monitoring", tags=["WebSocket Monitoring"])


@router.get("/health")
async def websocket_health_check():
    """
    WebSocket system health check endpoint
    Returns current health status and key metrics
    """
    try:
        health_status = get_websocket_monitor().get_health_status()

        return JSONResponse(
            status_code=200 if health_status["status"] == "healthy" else 503,
            content={
                "status": "success",
                "data": health_status,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Health check failed: {str(e)}",
                "timestamp": datetime.utcnow().isoformat(),
            },
        )


@router.get("/stats")
async def websocket_connection_stats():
    """
    Comprehensive WebSocket connection statistics
    """
    try:
        stats = get_websocket_monitor().get_connection_stats()

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
            status_code=500, detail=f"Failed to retrieve WebSocket statistics: {str(e)}"
        )


@router.get("/connections")
async def list_active_connections(
    session_id: Optional[str] = Query(None, description="Filter by session ID"),
    client_type: Optional[str] = Query(
        None, description="Filter by client type (admin/customer)"
    ),
    limit: int = Query(
        100, ge=1, le=1000, description="Maximum number of connections to return"
    ),
):
    """
    List active WebSocket connections with optional filtering
    """
    try:
        active_connections = get_websocket_monitor().get_active_connections()

        # Filter by session_id if provided
        if session_id:
            active_connections = {
                conn_id: metrics
                for conn_id, metrics in active_connections.items()
                if metrics.session_id == session_id
            }

        # Filter by client_type if provided
        if client_type:
            active_connections = {
                conn_id: metrics
                for conn_id, metrics in active_connections.items()
                if metrics.client_type == client_type
            }

        # Limit results
        connection_list = list(active_connections.items())[:limit]

        # Convert to serializable format
        serialized_connections = []
        for conn_id, metrics in connection_list:
            serialized_connections.append(
                {
                    "connection_id": conn_id,
                    "session_id": metrics.session_id,
                    "client_type": metrics.client_type,
                    "origin": metrics.origin,
                    "connect_time": metrics.connect_time.isoformat(),
                    "last_heartbeat": (
                        metrics.last_heartbeat.isoformat()
                        if metrics.last_heartbeat
                        else None
                    ),
                    "messages_sent": metrics.messages_sent,
                    "messages_received": metrics.messages_received,
                    "bytes_sent": metrics.bytes_sent,
                    "bytes_received": metrics.bytes_received,
                    "errors": metrics.errors,
                    "connection_duration": (
                        (datetime.utcnow() - metrics.connect_time).total_seconds()
                    ),
                }
            )

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "data": {
                    "connections": serialized_connections,
                    "total_count": len(active_connections),
                    "filtered_count": len(serialized_connections),
                    "filters": {
                        "session_id": session_id,
                        "client_type": client_type,
                        "limit": limit,
                    },
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve active connections: {str(e)}"
        )


@router.get("/sessions/{session_id}/connections")
async def get_session_connections(session_id: str):
    """
    Get all WebSocket connections for a specific session
    """
    try:
        session_connections = get_websocket_monitor().get_session_connections(
            session_id
        )

        if not session_connections:
            raise HTTPException(
                status_code=404,
                detail=f"No active WebSocket connections found for session {session_id}",
            )

        # Convert to serializable format
        serialized_connections = []
        for metrics in session_connections:
            serialized_connections.append(
                {
                    "session_id": metrics.session_id,
                    "client_type": metrics.client_type,
                    "origin": metrics.origin,
                    "connect_time": metrics.connect_time.isoformat(),
                    "last_heartbeat": (
                        metrics.last_heartbeat.isoformat()
                        if metrics.last_heartbeat
                        else None
                    ),
                    "messages_sent": metrics.messages_sent,
                    "messages_received": metrics.messages_received,
                    "bytes_sent": metrics.bytes_sent,
                    "bytes_received": metrics.bytes_received,
                    "errors": metrics.errors,
                    "connection_duration": (
                        (datetime.utcnow() - metrics.connect_time).total_seconds()
                    ),
                }
            )

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "data": {
                    "session_id": session_id,
                    "connections": serialized_connections,
                    "connection_count": len(serialized_connections),
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve session connections: {str(e)}"
        )


@router.get("/metrics/summary")
async def websocket_metrics_summary(
    hours: int = Query(
        1, ge=1, le=168, description="Number of hours to analyze (max 1 week)"
    )
):
    """
    WebSocket metrics summary for specified time period
    """
    try:
        # This would typically query a time-series database
        # For now, we'll return current statistics
        stats = get_websocket_monitor().get_connection_stats()
        health = get_websocket_monitor().get_health_status()

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "data": {
                    "time_period": {
                        "hours": hours,
                        "start_time": (
                            datetime.utcnow() - timedelta(hours=hours)
                        ).isoformat(),
                        "end_time": datetime.utcnow().isoformat(),
                    },
                    "current_stats": stats,
                    "health_status": health,
                    "note": "Historical metrics require time-series database integration",
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to generate metrics summary: {str(e)}"
        )


@router.post("/connections/{connection_id}/close")
async def force_close_connection(
    connection_id: str,
    reason: str = Query(
        "admin_forced_disconnect", description="Reason for forced disconnect"
    ),
):
    """
    Force close a specific WebSocket connection (admin function)
    """
    try:
        active_connections = get_websocket_monitor().get_active_connections()

        if connection_id not in active_connections:
            raise HTTPException(
                status_code=404,
                detail=f"WebSocket connection {connection_id} not found or already disconnected",
            )

        # Close the connection through the monitor
        from .websocket_monitor import DisconnectReason

        get_websocket_monitor().connection_closed(
            connection_id=connection_id, reason=DisconnectReason.SERVER_DISCONNECT
        )

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": f"WebSocket connection {connection_id} force-closed",
                "reason": reason,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to force close connection: {str(e)}"
        )


@router.get("/debug/prometheus-metrics")
async def get_prometheus_metrics():
    """
    Get current Prometheus metrics for WebSocket monitoring
    (Useful for debugging Prometheus integration)
    """
    try:
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        metrics_output = generate_latest().decode("utf-8")

        # Filter only WebSocket-related metrics
        websocket_metrics = []
        for line in metrics_output.split("\n"):
            if "websocket_" in line.lower():
                websocket_metrics.append(line)

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "data": {
                    "metrics_format": "prometheus",
                    "websocket_metrics": websocket_metrics,
                    "total_metric_lines": len(websocket_metrics),
                    "content_type": CONTENT_TYPE_LATEST,
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve Prometheus metrics: {str(e)}"
        )
