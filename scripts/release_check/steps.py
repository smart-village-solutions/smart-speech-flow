"""Run one check: time it, record it, and count a transport error as a failure."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

import httpx

from .evidence import Evidence
from .gateway import SocketRejected

Step = Callable[[], Awaitable[tuple[bool, str]]]

# A failed network call is a failed check, not a crashed run: the remaining
# checks and the cleanup must still happen.
_EXPECTED_FAILURES = (
    httpx.HTTPError,
    OSError,
    ValueError,
    KeyError,
    TimeoutError,
    SocketRejected,
)


async def run_step(evidence: Evidence, name: str, step: Step) -> bool:
    started = time.perf_counter()
    try:
        passed, detail = await step()
    except _EXPECTED_FAILURES as error:
        passed, detail = False, type(error).__name__
    evidence.record(name, passed, detail, int((time.perf_counter() - started) * 1000))
    return passed
