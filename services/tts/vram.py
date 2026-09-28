"""VRAM held by this process, read from NVML.

Inside a container NVML lists only the container's own processes, under their
container PIDs (checked on the production card on 2026-09-28: the TTS server
is PID 1), so the process finds itself by os.getpid(). torch's counters are no
substitute: they miss onnxruntime's CUDA arenas and the CUDA context.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ProcessVram:
    def __init__(self, nvml: Any, pid: int) -> None:
        self._nvml = nvml
        self._pid = pid
        self._initialised = False

    def read(self) -> int | None:
        """Bytes this process holds on all cards, or None when NVML cannot tell."""
        if self._nvml is None:
            return None
        try:
            if not self._initialised:
                self._nvml.nvmlInit()
                self._initialised = True
            held = [
                process.usedGpuMemory
                for index in range(self._nvml.nvmlDeviceGetCount())
                for process in self._nvml.nvmlDeviceGetComputeRunningProcesses(
                    self._nvml.nvmlDeviceGetHandleByIndex(index)
                )
                if process.pid == self._pid
            ]
        except Exception as exc:  # no NVML failure may break /health or /metrics
            logger.debug("NVML could not report this process's VRAM: %s", exc)
            return None
        if None in held:
            return None
        return sum(held)
