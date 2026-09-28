import logging
import threading
import time
from types import SimpleNamespace

from services.tts.vram import ProcessVram, VramBudget

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


class _Held:
    """A ProcessVram stand-in whose reading the test sets."""

    def __init__(self, held):
        self.held = held
        self.reads = 0

    def read(self, *, expect_context=False):
        self.reads += 1
        return self.held


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _budget(held, clock=None, on_gpu=True):
    return VramBudget(held, 1000 * MIB, on_gpu=on_gpu, clock=clock or _Clock())


def _budget_logs(caplog):
    return [(r.levelname, r.getMessage()) for r in caplog.records if "budget" in r.getMessage()]


def test_on_the_cpu_nothing_is_held_and_nvml_is_not_asked():
    held = _Held(None)
    budget = _budget(held, on_gpu=False)
    assert budget.read(expect_context=True) == 0
    assert budget.usage()["within_budget"] is True
    assert held.reads == 0


def test_on_a_gpu_an_unknown_reading_stays_unknown():
    assert _budget(_Held(None)).usage()["within_budget"] is None


def test_a_crossing_is_logged_only_once_it_has_lasted_five_minutes(caplog):
    caplog.set_level(logging.INFO, logger="services.tts.vram")
    clock = _Clock()
    budget = _budget(_Held(1500 * MIB), clock)
    for clock.now in (0, 100, 299):
        budget.usage()
    assert _budget_logs(caplog) == []
    for clock.now in (300, 400):
        budget.usage()
    assert _budget_logs(caplog) == [
        ("WARNING", "TTS has held over its 1000 MiB VRAM budget for 5 minutes: 1500 MiB")
    ]


def test_going_back_under_is_logged_once_and_restarts_the_window(caplog):
    caplog.set_level(logging.INFO, logger="services.tts.vram")
    clock = _Clock()
    held = _Held(1500 * MIB)
    budget = _budget(held, clock)
    for clock.now in (0, 300):
        budget.usage()
    held.held = 900 * MIB
    for clock.now in (310, 320):
        budget.usage()
    held.held = 1500 * MIB
    for clock.now in (330, 600):
        budget.usage()
    assert _budget_logs(caplog) == [
        ("WARNING", "TTS has held over its 1000 MiB VRAM budget for 5 minutes: 1500 MiB"),
        ("INFO", "TTS is back within its 1000 MiB VRAM budget: 900 MiB"),
    ]


def test_synthesis_peaks_are_never_logged(caplog):
    clock = _Clock()
    held = _Held(0)
    budget = _budget(held, clock)
    for minute in range(30):
        clock.now = minute * 60.0
        held.held = (1500 if minute % 2 else 900) * MIB
        budget.usage()
    assert _budget_logs(caplog) == []


def test_unknown_readings_neither_start_nor_end_the_window(caplog):
    clock = _Clock()
    held = _Held(1500 * MIB)
    budget = _budget(held, clock)
    budget.usage()
    held.held = None
    clock.now = 150
    budget.usage()
    held.held = 1500 * MIB
    clock.now = 300
    budget.usage()
    assert [level for level, _ in _budget_logs(caplog)] == ["WARNING"]


def test_concurrent_readings_log_a_crossing_once(caplog):
    """/health and /metrics read from Starlette's threadpool at the same time."""

    class _SlowClock(_Clock):
        def __call__(self):
            if self.now:
                time.sleep(0.05)
            return self.now

    clock = _SlowClock()
    budget = _budget(_Held(1500 * MIB), clock)
    budget.usage()
    clock.now = 300
    barrier = threading.Barrier(2)

    def read():
        barrier.wait()
        budget.usage()

    threads = [threading.Thread(target=read) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert [level for level, _ in _budget_logs(caplog)] == ["WARNING"]
