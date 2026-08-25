"""Shared resource and auto-scaling helpers for model services."""

from typing import Any, Callable, Dict, List


def get_system_stats(psutil_module: Any) -> Dict[str, Any]:
    """Return the lightweight CPU and memory values used in debug payloads."""
    if psutil_module is None:
        return {"cpu": None, "ram": None}

    try:
        return {
            "cpu": psutil_module.cpu_percent(),
            "ram": psutil_module.virtual_memory().percent,
        }
    except Exception:  # pragma: no cover - psutil rarely fails at runtime
        return {"cpu": None, "ram": None}


def collect_resource_metrics(
    psutil_module: Any, collect_gpu: Callable[[], Dict[str, Any]]
) -> Dict[str, Any]:
    """Gather CPU, memory and service-specific GPU statistics."""
    metrics: Dict[str, Any] = {
        "cpu_percent": None,
        "memory_percent": None,
        "memory_total": None,
        "memory_available": None,
        "gpu": collect_gpu(),
    }

    if psutil_module is None:
        metrics["psutil_error"] = "psutil_not_installed"
        return metrics

    try:
        metrics["cpu_percent"] = psutil_module.cpu_percent(interval=None)
        virtual_mem = psutil_module.virtual_memory()
        metrics["memory_percent"] = virtual_mem.percent
        metrics["memory_total"] = virtual_mem.total
        metrics["memory_available"] = virtual_mem.available
    except Exception as exc:  # pragma: no cover - psutil rarely fails
        metrics["psutil_error"] = str(exc)

    return metrics


def derive_auto_scaling_signal(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Recommend scale-up when CPU, memory or a GPU reaches 85 percent."""
    threshold = 85
    reasons: List[str] = []

    if (
        cpu_percent := metrics.get("cpu_percent")
    ) is not None and cpu_percent >= threshold:
        reasons.append(f"cpu>={threshold}")
    if (
        memory_percent := metrics.get("memory_percent")
    ) is not None and memory_percent >= threshold:
        reasons.append(f"memory>={threshold}")

    for device in metrics.get("gpu", {}).get("devices", []):
        append_gpu_signal(reasons, device, threshold)

    return {
        "recommended_action": "scale_up" if reasons else "steady",
        "reasons": reasons,
    }


def append_gpu_signal(
    reasons: List[str], gpu_device: Dict[str, Any], threshold: int
) -> None:
    """Append scale-up reasons for a GPU that crosses the threshold."""
    if (
        gpu_util := gpu_device.get("utilization_percent")
    ) is not None and gpu_util >= threshold:
        reasons.append(f"gpu{gpu_device.get('index')}_util>={threshold}")
    if (
        memory_util := gpu_device.get("memory_utilization")
    ) is not None and memory_util >= threshold:
        reasons.append(f"gpu{gpu_device.get('index')}_mem>={threshold}")
