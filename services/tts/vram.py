"""VRAM held by this process, read from NVML.

Inside a container NVML lists only the container's own processes, under their
container PIDs (checked on the production card on 2026-09-28: the TTS server
is PID 1), so the process finds itself by os.getpid(). torch's counters are no
substitute: they miss onnxruntime's CUDA arenas and the CUDA context.
"""

import logging
import threading
import time
from typing import Any, Callable, Dict

logger = logging.getLogger(__name__)

MIB = 1024 * 1024


class ProcessVram:
    def __init__(self, nvml: Any, pid: int) -> None:
        self._nvml = nvml
        self._pid = pid
        self._initialised = False

    def read(self, *, expect_context: bool = False) -> int | None:
        """Bytes this process holds on all cards, or None when NVML cannot tell.

        A process with no CUDA context is not listed at all, which means it
        holds nothing. Once it must hold one, not being listed means NVML is
        reporting PIDs from another namespace, and 0 would be a lie.
        """
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
        if not held:
            return None if expect_context else 0
        if None in held:
            return None
        return sum(held)


class VramBudget:
    """The process's VRAM held against TTS_VRAM_BUDGET_MIB.

    On the CPU the process holds nothing by construction, so NVML is not
    asked: a CPU host without NVML must not read as unknown and fire
    TTSVRAMUnknown. A crossing is logged the way TTSVRAMOverBudget sees it,
    only once every reading for five minutes has been over: a synthesis in
    flight lifts single readings for well under a second.
    """

    SUSTAIN_SECONDS = 300.0

    def __init__(
        self,
        vram: Any,
        budget_bytes: int,
        *,
        on_gpu: bool,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.budget_bytes = budget_bytes
        self.voice_bytes: Dict[str, int] = {}
        self.voices_loaded = False
        self._vram = vram
        self._on_gpu = on_gpu
        self._clock = clock
        self._lock = threading.Lock()
        self._over_since: float | None = None
        self._warned = False

    def read(self, *, expect_context: bool) -> int | None:
        if not self._on_gpu:
            return 0
        return self._vram.read(expect_context=expect_context)

    def usage(self) -> Dict[str, Any]:
        """Read the VRAM now, compare it with the budget, log a lasting crossing."""
        held = self.read(expect_context=self.voices_loaded)
        if held is not None:
            self._observe(held)
        return {
            "process_bytes": held,
            "budget_bytes": self.budget_bytes,
            "within_budget": None if held is None else held <= self.budget_bytes,
            "voice_load_bytes": dict(self.voice_bytes),
        }

    def _observe(self, held: int) -> None:
        budget_mib = self.budget_bytes // MIB
        with self._lock:
            if held <= self.budget_bytes:
                self._over_since = None
                if self._warned:
                    self._warned = False
                    logger.info(
                        "TTS is back within its %d MiB VRAM budget: %d MiB", budget_mib, held // MIB
                    )
            elif self._over_since is None:
                self._over_since = self._clock()
            elif not self._warned and self._clock() - self._over_since >= self.SUSTAIN_SECONDS:
                self._warned = True
                logger.warning(
                    "TTS has held over its %d MiB VRAM budget for 5 minutes: %d MiB",
                    budget_mib,
                    held // MIB,
                )
