from types import SimpleNamespace

from services.tts.vram import ProcessVram

MIB = 1024 * 1024


class _Nvml:
    def __init__(self, cards, *, init_error=None):
        self.cards = cards
        self.init_error = init_error
        self.init_calls = 0
        self.nvmlInit = self._init
        self.nvmlDeviceGetCount = lambda: len(self.cards)
        self.nvmlDeviceGetHandleByIndex = lambda index: index
        self.nvmlDeviceGetComputeRunningProcesses = self._processes

    def _init(self):
        self.init_calls += 1
        if self.init_error:
            raise self.init_error

    def _processes(self, handle):
        return [SimpleNamespace(pid=pid, usedGpuMemory=used) for pid, used in self.cards[handle]]


def test_counts_only_this_process_on_every_card():
    nvml = _Nvml([[(7, 300 * MIB), (8, 9000 * MIB)], [(7, 50 * MIB)]])
    assert ProcessVram(nvml, pid=7).read() == 350 * MIB


def test_a_process_without_a_cuda_context_holds_nothing():
    assert ProcessVram(_Nvml([[(8, 9000 * MIB)]]), pid=7).read() == 0


def test_nvml_is_initialised_once():
    nvml = _Nvml([[(7, MIB)]])
    vram = ProcessVram(nvml, pid=7)
    vram.read()
    vram.read()
    assert nvml.init_calls == 1


def test_unknown_without_nvml():
    assert ProcessVram(None, pid=7).read() is None


def test_unknown_when_nvml_cannot_start():
    nvml = _Nvml([], init_error=RuntimeError("NVML Shared Library Not Found"))
    assert ProcessVram(nvml, pid=7).read() is None


def test_unknown_when_the_driver_does_not_report_per_process_memory():
    assert ProcessVram(_Nvml([[(7, None)]]), pid=7).read() is None


def test_unknown_when_a_process_that_must_hold_a_context_is_not_listed():
    """NVML reporting host PIDs would otherwise read as "holds nothing"."""
    assert ProcessVram(_Nvml([[(8, 9000 * MIB)]]), pid=7).read(expect_context=True) is None


def test_a_listed_process_is_read_whether_or_not_a_context_is_expected():
    assert ProcessVram(_Nvml([[(7, 20 * MIB)]]), pid=7).read(expect_context=True) == 20 * MIB
