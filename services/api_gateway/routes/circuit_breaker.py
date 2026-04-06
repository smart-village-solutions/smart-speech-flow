"""
Circuit Breaker Health Routes für Smart Speech Flow Backend
===========================================================

HTTP Endpoints für Circuit Breaker und Service Health Monitoring:
- Service Health Status
- Circuit Breaker Status
- Degradation Information
- Manual Circuit Control (Admin)

Autor: Smart Village Solutions
Datum: November 2025
Version: 1.0
"""

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, status

from ..circuit_breaker import CircuitBreakerFactory
from ..circuit_breaker_client import circuit_breaker_client
from ..graceful_degradation import graceful_degradation_manager

logger = logging.getLogger(__name__)

router = APIRouter()

CIRCUIT_BREAKER_ROUTE_RESPONSES = {
    400: {"description": "Invalid service name"},
    404: {"description": "Service or circuit breaker not found"},
    500: {"description": "Circuit breaker health operation failed"},
}


@router.get(
    "/health/services",
    responses={500: {"description": "Health status lookup failed"}},
)
async def get_services_health() -> Dict[str, Any]:
    """
    Gesamter Health Status aller Services

    Returns:
        Service Health Overview mit Circuit Breaker Status
    """
    try:
        health_status = await circuit_breaker_client.get_health_status()
        return {
            "status": "success",
            "data": health_status,
            "timestamp": health_status.get("monitoring_info", {}).get("last_check"),
        }
    except Exception as e:
        logger.error(f"❌ Health Status Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Health status check failed: {str(e)}",
        )


@router.get(
    "/health/services/{service_name}",
    responses=CIRCUIT_BREAKER_ROUTE_RESPONSES,
)
async def get_service_health(service_name: str) -> Dict[str, Any]:
    """
    Health Status für einzelnen Service

    Args:
        service_name: Name des Services (asr, translation, tts)

    Returns:
        Detaillierter Service Health Status
    """
    if service_name not in ["asr", "translation", "tts"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown service: {service_name}. Valid services: asr, translation, tts",
        )

    try:
        service_status = await circuit_breaker_client.get_service_status(service_name)

        if service_status is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Service '{service_name}' not found or not registered",
            )

        return {
            "status": "success",
            "service_name": service_name,
            "data": service_status,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Service Health Error for {service_name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Service health check failed: {str(e)}",
        )


@router.get(
    "/health/circuit-breakers",
    responses={500: {"description": "Circuit breaker status lookup failed"}},
)
async def get_circuit_breakers_status() -> Dict[str, Any]:
    """
    Status aller Circuit Breaker

    Returns:
        Circuit Breaker Status für alle Services
    """
    try:
        circuits = CircuitBreakerFactory.get_all_circuits()

        circuit_status = {}
        for name, circuit in circuits.items():
            circuit_status[name] = circuit.get_health_status()

        return {
            "status": "success",
            "total_circuits": len(circuits),
            "circuits": circuit_status,
        }
    except Exception as e:
        logger.error(f"❌ Circuit Breaker Status Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Circuit breaker status check failed: {str(e)}",
        )


@router.get(
    "/health/degradation",
    responses={500: {"description": "Degradation status lookup failed"}},
)
async def get_degradation_status() -> Dict[str, Any]:
    """
    Graceful Degradation Status

    Returns:
        Cache Status, Service Mode, Fallback Information
    """
    try:
        degradation_status = await circuit_breaker_client.get_degradation_status()

        return {"status": "success", "data": degradation_status}
    except Exception as e:
        logger.error(f"❌ Degradation Status Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Degradation status check failed: {str(e)}",
        )


@router.post(
    "/admin/circuit-breakers/{service_name}/reset",
    responses=CIRCUIT_BREAKER_ROUTE_RESPONSES,
)
async def reset_circuit_breaker(service_name: str) -> Dict[str, Any]:
    """
    Manueller Circuit Breaker Reset (Admin Only)

    Args:
        service_name: Name des Services

    Returns:
        Reset Status
    """
    if service_name not in ["asr", "translation", "tts"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown service: {service_name}. Valid services: asr, translation, tts",
        )

    try:
        circuits = CircuitBreakerFactory.get_all_circuits()

        if service_name not in circuits:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Circuit breaker for service '{service_name}' not found",
            )

        # Manual Reset
        circuit = circuits[service_name]
        old_state = circuit.state
        circuit.reset()

        logger.warning(
            f"⚠️ Manual Circuit Breaker Reset: {service_name} ({old_state.value} → CLOSED)"
        )

        return {
            "status": "success",
            "message": f"Circuit breaker for '{service_name}' has been reset",
            "service_name": service_name,
            "old_state": old_state.value,
            "new_state": "closed",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Circuit Breaker Reset Error for {service_name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Circuit breaker reset failed: {str(e)}",
        )


@router.post(
    "/admin/circuit-breakers/reset-all",
    responses={500: {"description": "Circuit breaker reset failed"}},
)
async def reset_all_circuit_breakers() -> Dict[str, Any]:
    """
    Manueller Reset aller Circuit Breaker (Admin Only)

    Returns:
        Reset Status aller Circuit Breaker
    """
    try:
        circuits = CircuitBreakerFactory.get_all_circuits()

        reset_results = {}
        for name, circuit in circuits.items():
            old_state = circuit.state
            circuit.reset()
            reset_results[name] = {"old_state": old_state.value, "new_state": "closed"}

        logger.warning(f"⚠️ Manual Reset ALL Circuit Breakers: {list(circuits.keys())}")

        return {
            "status": "success",
            "message": f"All {len(circuits)} circuit breakers have been reset",
            "total_reset": len(circuits),
            "results": reset_results,
        }

    except Exception as e:
        logger.error(f"❌ All Circuit Breakers Reset Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Circuit breakers reset failed: {str(e)}",
        )


@router.get(
    "/health/cache",
    responses={500: {"description": "Cache status lookup failed"}},
)
async def get_cache_status() -> Dict[str, Any]:
    """
    Fallback Cache Status

    Returns:
        Cache Statistics und Performance Metrics
    """
    try:
        degradation_status = graceful_degradation_manager.get_degradation_status()
        cache_info = {
            "cache_size": degradation_status["cache_size"],
            "cache_stats": degradation_status["cache_stats"],
            "pending_requests": degradation_status["pending_requests"],
            "current_mode": degradation_status["current_mode"],
        }

        return {"status": "success", "data": cache_info}

    except Exception as e:
        logger.error(f"❌ Cache Status Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Cache status check failed: {str(e)}",
        )


@router.delete(
    "/admin/cache/clear",
    responses={500: {"description": "Cache clear failed"}},
)
async def clear_fallback_cache() -> Dict[str, Any]:
    """
    Leert Fallback Cache (Admin Only)

    Returns:
        Clear Status
    """
    try:
        # Cache Statistics vor dem Leeren
        old_stats = graceful_degradation_manager.get_degradation_status()
        old_cache_size = old_stats["cache_size"]

        # Cache leeren
        graceful_degradation_manager.response_cache.clear()
        graceful_degradation_manager.cache_stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
        }

        logger.warning(f"⚠️ Fallback Cache cleared: {old_cache_size} entries removed")

        return {
            "status": "success",
            "message": "Fallback cache cleared successfully",
            "entries_removed": old_cache_size,
            "cache_stats_reset": True,
        }

    except Exception as e:
        logger.error(f"❌ Cache Clear Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Cache clear failed: {str(e)}",
        )


@router.get(
    "/health/summary",
    responses={500: {"description": "Health summary generation failed"}},
)
async def get_health_summary() -> Dict[str, Any]:
    """
    Kompakte Health Summary für Dashboard

    Returns:
        Übersicht über Service Health, Circuit Breaker und Cache
    """
    try:
        # Service Health
        health_status = await circuit_breaker_client.get_health_status()
        summary = health_status.get("summary", {})
        gpu_summary = health_status.get("gpu_summary", {})

        # Circuit Breaker States
        circuits = CircuitBreakerFactory.get_all_circuits()
        circuit_states = {
            name: circuit.state.value for name, circuit in circuits.items()
        }

        # Degradation Info
        degradation_status = await circuit_breaker_client.get_degradation_status()

        gpu_overview = {
            "devices_reporting": gpu_summary.get("devices_reporting", 0),
            "services_reporting": gpu_summary.get("services_reporting", 0),
            "critical_devices": gpu_summary.get("critical_devices", 0),
            "warning_devices": gpu_summary.get("warning_devices", 0),
            "scale_up_recommendations": gpu_summary.get("scale_up_recommendations", 0),
            "recommended_action": gpu_summary.get("recommended_action", "steady"),
        }

        return {
            "status": "success",
            "overall_healthy": health_status.get("overall_healthy", False),
            "summary": {
                "services": summary,
                "circuit_states": circuit_states,
                "service_mode": degradation_status.get("current_mode", "unknown"),
                "cache_entries": degradation_status.get("cache_size", 0),
                "pending_requests": degradation_status.get("pending_requests", 0),
                "gpu": gpu_overview,
            },
            "gpu_summary": gpu_summary,
            "alerts": _generate_health_alerts(
                health_status, circuit_states, degradation_status, gpu_summary
            ),
        }

    except Exception as e:
        logger.error(f"❌ Health Summary Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Health summary generation failed: {str(e)}",
        )


def _generate_health_alerts(
    health_status: Dict,
    circuit_states: Dict,
    degradation_status: Dict,
    gpu_summary: Dict,
) -> List[Dict[str, str]]:
    """Generiert Health Alerts für Dashboard"""
    alerts = []

    # Service Health Alerts
    unhealthy_services = health_status.get("services", {}).get("unhealthy", [])
    for service in unhealthy_services:
        alerts.append(
            {
                "level": "error",
                "type": "service_down",
                "message": f"Service '{service}' ist nicht verfügbar",
            }
        )

    # Circuit Breaker Alerts
    for service, state in circuit_states.items():
        if state == "open":
            alerts.append(
                {
                    "level": "error",
                    "type": "circuit_open",
                    "message": f"Circuit Breaker für '{service}' ist OPEN",
                }
            )
        elif state == "half_open":
            alerts.append(
                {
                    "level": "warning",
                    "type": "circuit_testing",
                    "message": f"Circuit Breaker für '{service}' testet Recovery",
                }
            )

    # Degradation Alerts
    current_mode = degradation_status.get("current_mode", "full")
    if current_mode != "full":
        alerts.append(
            {
                "level": "warning",
                "type": "degraded_mode",
                "message": f"System läuft im {current_mode.upper()} Modus",
            }
        )

    # Cache Alerts
    cache_size = degradation_status.get("cache_size", 0)
    if cache_size > 800:  # Near max cache size
        alerts.append(
            {
                "level": "info",
                "type": "cache_full",
                "message": f"Fallback Cache fast voll ({cache_size} Einträge)",
            }
        )

    # GPU Alerts
    for gpu_alert in gpu_summary.get("alerts", []):
        severity = gpu_alert.get("severity", "warning")
        level = "error" if severity == "critical" else "warning"
        alerts.append(
            {
                "level": level,
                "type": "gpu_pressure",
                "message": (
                    f"GPU Druck: {gpu_alert.get('service')} GPU{gpu_alert.get('device')} "
                    f"{gpu_alert.get('message')}"
                ),
            }
        )

    for service in gpu_summary.get("services_missing_gpu", []):
        alerts.append(
            {
                "level": "info",
                "type": "gpu_unavailable",
                "message": f"Service '{service}' meldet keine verfügbare GPU",
            }
        )

    return alerts
