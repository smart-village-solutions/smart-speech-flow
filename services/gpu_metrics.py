from typing import Any, Dict, Tuple


def _build_base_gpu_info(torch_module: Any) -> Dict[str, Any]:
    gpu_available = bool(torch_module.cuda.is_available())
    return {
        "available": gpu_available,
        "device_count": torch_module.cuda.device_count() if gpu_available else 0,
        "devices": [],
        "errors": [],
    }


def _initialize_nvml(
    pynvml_module: Any, nvml_initialized: bool, gpu_info: Dict[str, Any]
) -> Tuple[bool, bool]:
    if pynvml_module is None:
        return False, nvml_initialized

    try:
        if not nvml_initialized:
            pynvml_module.nvmlInit()
            nvml_initialized = True
        return True, nvml_initialized
    except Exception as exc:  # pragma: no cover - hardware specific branch
        gpu_info["errors"].append(f"nvml_init_failed: {exc}")
        return False, nvml_initialized


def _collect_device_metrics(
    torch_module: Any, pynvml_module: Any, device_idx: int, nvml_ready: bool
) -> Tuple[Dict[str, Any], list[str]]:
    device_data: Dict[str, Any] = {"index": device_idx}
    errors: list[str] = []

    try:
        props = torch_module.cuda.get_device_properties(device_idx)
        torch_alloc = torch_module.cuda.memory_allocated(device_idx)
        torch_reserved = torch_module.cuda.memory_reserved(device_idx)
        device_data.update(
            {
                "name": props.name,
                "total_memory": props.total_memory,
                "memory_allocated": torch_alloc,
                "memory_reserved": torch_reserved,
                "memory_utilization": None,
                "utilization_percent": None,
                "temperature_c": None,
            }
        )
        if nvml_ready:
            try:
                handle = pynvml_module.nvmlDeviceGetHandleByIndex(device_idx)
                util = pynvml_module.nvmlDeviceGetUtilizationRates(handle)
                mem = pynvml_module.nvmlDeviceGetMemoryInfo(handle)
                device_data["memory_utilization"] = (
                    round(mem.used / mem.total * 100, 2) if mem.total else None
                )
                device_data["utilization_percent"] = util.gpu
                device_data["temperature_c"] = pynvml_module.nvmlDeviceGetTemperature(
                    handle, pynvml_module.NVML_TEMPERATURE_GPU
                )
                device_data["memory_total_nvml"] = mem.total
                device_data["memory_used_nvml"] = mem.used
            except Exception as exc:  # pragma: no cover - hardware specific branch
                errors.append(f"nvml_query_failed_gpu_{device_idx}: {exc}")
    except Exception as exc:  # pragma: no cover - hardware specific branch
        errors.append(f"torch_query_failed_gpu_{device_idx}: {exc}")

    return device_data, errors


def collect_gpu_metrics(
    torch_module: Any, pynvml_module: Any, nvml_initialized: bool
) -> Tuple[Dict[str, Any], bool]:
    gpu_info = _build_base_gpu_info(torch_module)
    if not gpu_info["available"]:
        return gpu_info, nvml_initialized

    nvml_ready, nvml_initialized = _initialize_nvml(
        pynvml_module, nvml_initialized, gpu_info
    )

    for device_idx in range(gpu_info["device_count"]):
        device_data, device_errors = _collect_device_metrics(
            torch_module, pynvml_module, device_idx, nvml_ready
        )
        gpu_info["devices"].append(device_data)
        gpu_info["errors"].extend(device_errors)

    return gpu_info, nvml_initialized
