"""Ephemeral, bounded laboratory translation; never stores or logs content."""

from __future__ import annotations

import asyncio
import math
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, TypeVar
from uuid import uuid4

import requests
from prometheus_client import CollectorRegistry, Counter, Histogram
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from .circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from .speech_services import TRANSLATION_URL

T = TypeVar("T")
_LANGUAGE = re.compile(r"^[a-z]{2,3}$")


class TranslationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: list[StrictStr] = Field(
        description="1–10 nonblank strings, at most 5,000 Unicode code points in total."
    )
    source_lang: StrictStr
    target_lang: StrictStr


class TranslationItem(BaseModel):
    text: str


class TranslationResponse(BaseModel):
    translations: list[TranslationItem]
    source_lang: str
    target_lang: str


class LanguagesResponse(BaseModel):
    languages: list[str]


class TranslationError(Exception):
    """A safe public failure; messages never derive from upstream bodies."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        limits: dict[str, int] | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message
        self.limits = limits
        self.retry_after = retry_after


def deadline_error() -> TranslationError:
    return TranslationError(504, "DEADLINE_EXCEEDED", "Translation deadline exceeded.")


def unavailable() -> TranslationError:
    return TranslationError(503, "UNAVAILABLE", "Text translation is unavailable.", retry_after=1)


@dataclass(frozen=True)
class TextTranslationConfig:
    enabled: bool = False
    internal_token: str = ""
    languages: tuple[str, ...] = ("de", "en", "fr", "es", "ar", "tr")
    body_bytes: int = 65_536
    max_characters: int = 5_000
    max_items: int = 10
    queue_size: int = 4
    deadline_seconds: float = 30.0
    requests_per_minute: int = 6
    tracked_ips: int = 1_024

    def __post_init__(self) -> None:
        counts = (
            self.body_bytes,
            self.max_characters,
            self.max_items,
            self.requests_per_minute,
            self.tracked_ips,
        )
        if any(type(value) is not int or value <= 0 for value in counts):
            raise ValueError("text translation limits must be positive integers")
        if type(self.queue_size) is not int or self.queue_size < 0:
            raise ValueError("text translation queue must be finite")
        if not math.isfinite(self.deadline_seconds) or not 0 < self.deadline_seconds <= 30:
            raise ValueError("text translation deadline must be finite and positive")
        if not self.languages or any(not _LANGUAGE.fullmatch(x) for x in self.languages):
            raise ValueError("text translation languages must be canonical service codes")

    @classmethod
    def from_environment(cls) -> TextTranslationConfig:
        languages = tuple(
            x.strip()
            for x in os.getenv("SSF_TEXT_TRANSLATION_LANGUAGES", "de,en,fr,es,ar,tr").split(",")
            if x.strip()
        )
        return cls(
            enabled=os.getenv("SSF_TEXT_TRANSLATION_ENABLED", "0") == "1",
            internal_token=os.getenv("SSF_TEXT_TRANSLATION_INTERNAL_TOKEN", "").strip(),
            languages=languages,
        )


class TextTranslationMetrics:
    """Aggregate outcomes and latency; no content or caller labels."""

    def __init__(self, registry: CollectorRegistry) -> None:
        self.requests = Counter(
            "text_translation_requests_total",
            "Laboratory translation HTTP outcomes",
            ["operation", "outcome"],
            registry=registry,
        )
        self.latency = Histogram(
            "text_translation_request_seconds",
            "Laboratory translation HTTP latency",
            ["operation"],
            registry=registry,
        )

    def observe(self, operation: str, outcome: str, started: float) -> None:
        self.requests.labels(operation, outcome).inc()
        self.latency.labels(operation).observe(max(0, time.monotonic() - started))


class TextTranslationService:
    """One scheduler per app: four waiters, one worker, finite caller tracking.

    A cancelled HTTP waiter does not cancel its worker task. Its worker holds
    the scheduling lock until the synchronous transport really returns.
    """

    def __init__(
        self,
        breaker: CircuitBreaker,
        config: TextTranslationConfig,
        *,
        background_busy: Callable[[], bool] | None = None,
        metrics: TextTranslationMetrics | None = None,
    ) -> None:
        self.config = config
        self.metrics = metrics or TextTranslationMetrics(CollectorRegistry())
        self._background_busy = background_busy
        self._active_requests: dict[str, threading.Event] = {}
        self._request_lock = threading.Lock()
        self._breaker = breaker
        self._base_url = TRANSLATION_URL.rsplit("/", 1)[0]
        self._lock = asyncio.Lock()
        self._pending = 0
        self._workers: set[asyncio.Task[Any]] = set()
        self._callers: dict[str, deque[float]] = {}

    def request_cancelled(self, request_id: str) -> bool | None:
        """Private activity callback lookup; IDs disappear with their worker."""
        with self._request_lock:
            event = self._active_requests.get(request_id)
            return event.is_set() if event is not None else None

    def _deadline_error(self) -> TranslationError:
        if self._background_busy is not None and self._background_busy():
            return TranslationError(
                503, "SYSTEM_BUSY", "Translation system is busy.", retry_after=1
            )
        return deadline_error()

    def check_available(self) -> None:
        if not self.config.enabled:
            raise TranslationError(404, "NOT_FOUND", "Not found.")
        if not self.config.internal_token:
            raise unavailable()

    def admit_caller(self, ip: str) -> None:
        now = time.monotonic()
        expired = [key for key, entries in self._callers.items() if entries[-1] <= now - 60]
        for key in expired:
            del self._callers[key]
        entries = self._callers.get(ip)
        if entries is None:
            if len(self._callers) >= self.config.tracked_ips:
                raise TranslationError(
                    503, "SYSTEM_BUSY", "Caller capacity reached.", retry_after=60
                )
            entries = self._callers[ip] = deque()
        while entries and entries[0] <= now - 60:
            entries.popleft()
        if len(entries) >= self.config.requests_per_minute:
            raise TranslationError(
                429,
                "RATE_LIMIT_EXCEEDED",
                "Too many requests.",
                retry_after=max(1, math.ceil(60 - (now - entries[0]))),
            )
        entries.append(now)

    def validate(self, payload: TranslationRequest) -> None:
        if len(payload.text) > self.config.max_items:
            raise TranslationError(
                413,
                "ITEM_LIMIT_EXCEEDED",
                "Too many text entries.",
                limits={"max_items": self.config.max_items},
            )
        if sum(len(value) for value in payload.text) > self.config.max_characters:
            raise TranslationError(
                413,
                "CHARACTER_LIMIT_EXCEEDED",
                "Text exceeds the character limit.",
                limits={"max_characters": self.config.max_characters},
            )
        try:
            for value in payload.text:
                value.encode("utf-8")
        except UnicodeEncodeError:
            raise TranslationError(
                422, "INVALID_REQUEST", "Text must contain valid Unicode."
            ) from None
        if not payload.text or any(not value.strip() for value in payload.text):
            raise TranslationError(422, "INVALID_REQUEST", "Text entries must be nonblank strings.")
        if any(
            not _LANGUAGE.fullmatch(code) for code in (payload.source_lang, payload.target_lang)
        ):
            raise TranslationError(
                422, "INVALID_REQUEST", "Language codes must be canonical lowercase service codes."
            )

    @staticmethod
    def _remaining(deadline: float, cancelled: threading.Event) -> float:
        remaining = deadline - time.monotonic()
        if cancelled.is_set() or remaining <= 0:
            raise deadline_error()
        return remaining

    async def _submit(self, operation: Callable[[threading.Event], T], deadline: float) -> T:
        if self._pending >= self.config.queue_size + 1:
            raise TranslationError(503, "SYSTEM_BUSY", "Translation queue is full.", retry_after=1)
        self._pending += 1
        acquired = False
        transferred = False
        cancelled = threading.Event()
        try:
            async with asyncio.timeout(max(0, deadline - time.monotonic())):
                await self._lock.acquire()
                acquired = True
                self._remaining(deadline, cancelled)

                async def run() -> T:
                    try:
                        return await asyncio.to_thread(operation, cancelled)
                    finally:
                        self._pending -= 1
                        self._lock.release()

                task = asyncio.create_task(run())
                transferred = True
                self._workers.add(task)

                def finished(worker: asyncio.Task[T]) -> None:
                    self._workers.discard(worker)
                    # Consume failures for disconnected/expired waiters.
                    if not worker.cancelled():
                        worker.exception()

                task.add_done_callback(finished)
                return await asyncio.shield(task)
        except TimeoutError:
            cancelled.set()
            if not acquired:
                raise TranslationError(
                    503, "SYSTEM_BUSY", "Translation queue is busy.", retry_after=1
                ) from None
            raise self._deadline_error() from None
        except asyncio.CancelledError:
            cancelled.set()
            raise
        finally:
            if not transferred:
                self._pending -= 1
                if acquired:
                    self._lock.release()

    def _capabilities(self, deadline: float, cancelled: threading.Event) -> list[str]:
        remaining = self._remaining(deadline, cancelled)
        try:
            # Discovery never takes a half-open inference probe or changes
            # inference health. The strict POST uses the registered breaker.
            response = requests.get(f"{self._base_url}/languages", timeout=remaining)
            if response.status_code != 200:
                raise unavailable()
            try:
                languages = response.json()["languages"]
            except (ValueError, KeyError, TypeError, RecursionError):
                raise unavailable() from None
            if (
                not isinstance(languages, list)
                or not languages
                or any(
                    not isinstance(code, str) or not _LANGUAGE.fullmatch(code) for code in languages
                )
            ):
                raise unavailable()
            result = sorted(set(languages).intersection(self.config.languages))
            if not result:
                raise unavailable()
            return result
        except requests.Timeout:
            raise self._deadline_error() from None
        except requests.RequestException:
            raise unavailable() from None

    async def languages(self, deadline: float) -> list[str]:
        return await self._submit(
            lambda cancelled: self._capabilities(deadline, cancelled), deadline
        )

    async def translate(self, payload: TranslationRequest, deadline: float) -> list[str]:
        return await self._submit(
            lambda cancelled: self._translate(payload, deadline, cancelled), deadline
        )

    def _translate(
        self, payload: TranslationRequest, deadline: float, cancelled: threading.Event
    ) -> list[str]:
        languages = self._capabilities(deadline, cancelled)
        self._remaining(deadline, cancelled)
        if payload.source_lang not in languages or payload.target_lang not in languages:
            raise TranslationError(422, "UNSUPPORTED_LANGUAGE", "Unsupported language code.")
        if payload.source_lang == payload.target_lang:
            return list(payload.text)
        request_id = uuid4().hex
        with self._request_lock:
            self._active_requests[request_id] = cancelled
        try:
            return self._strict_post(payload, deadline, cancelled, request_id)
        finally:
            with self._request_lock:
                self._active_requests.pop(request_id, None)

    def _strict_post(
        self,
        payload: TranslationRequest,
        deadline: float,
        cancelled: threading.Event,
        request_id: str,
    ) -> list[str]:
        remaining = self._remaining(deadline, cancelled)
        # Leave response/serialization time inside the gateway's total budget.
        if remaining <= 0.25:
            raise self._deadline_error()
        try:
            with self._breaker.guard(allow_recovery=False):
                started = time.monotonic()
                response = requests.post(
                    f"{self._base_url}/translate/text",
                    json={
                        **payload.model_dump(),
                        "timeout_seconds": remaining - 0.25,
                        "request_id": request_id,
                    },
                    headers={"X-SSF-Lab-Token": self.config.internal_token},
                    timeout=remaining,
                )
                if response.status_code != 200:
                    raise self._upstream_error(response)
                result = self._validate_result(response, len(payload.text))
                self._breaker.record_success(time.monotonic() - started)
                self._remaining(deadline, cancelled)
                return result
        except CircuitBreakerOpenError:
            raise unavailable() from None
        except requests.Timeout:
            raise self._deadline_error() from None
        except requests.RequestException:
            self._breaker.record_failure("Strict translation transport failed")
            raise unavailable() from None

    def _unusable_result(self) -> TranslationError:
        self._breaker.record_failure("Strict translation returned an unusable result")
        return TranslationError(
            502, "UNUSABLE_RESULT", "Translation service returned an unusable result."
        )

    def _validate_result(self, response: requests.Response, count: int) -> list[str]:
        try:
            result = response.json()["translations"]
        except (ValueError, TypeError, KeyError, RecursionError):
            raise self._unusable_result() from None
        if (
            not isinstance(result, list)
            or len(result) != count
            or any(not isinstance(value, str) or not value.strip() for value in result)
        ):
            raise self._unusable_result()
        try:
            for value in result:
                value.encode("utf-8")
        except UnicodeEncodeError:
            raise self._unusable_result() from None
        return result

    def _upstream_error(self, response: requests.Response) -> TranslationError:
        try:
            detail = response.json().get("detail", {})
            code = detail.get("code")
        except (ValueError, TypeError, AttributeError, RecursionError):
            detail, code = {}, None
        status = response.status_code
        if status == 413:
            return self._work_limit_error(detail)
        # Expected strict failures never break live conversation inference.
        expected = {
            504: deadline_error(),
            502: TranslationError(
                502, "INCOMPLETE_TRANSLATION", "Translation could not be completed."
            ),
            400: TranslationError(422, "INVALID_REQUEST", "Translation request was rejected."),
            422: TranslationError(422, "INVALID_REQUEST", "Translation request was rejected."),
        }
        if status in expected:
            return expected[status]
        if status == 503:
            if code in ("SYSTEM_BUSY", "SATURATED"):
                return TranslationError(
                    503, "SYSTEM_BUSY", "Translation system is busy.", retry_after=1
                )
            return unavailable()
        if status >= 500:
            self._breaker.record_failure("Strict translation service failed")
        return unavailable()

    def _work_limit_error(self, detail: Any) -> TranslationError:
        recognized = {
            "max_body_bytes",
            "max_items",
            "max_characters",
            "max_segments",
            "input_tokens",
            "max_attempts",
            "total_output_tokens",
            "output_tokens",
        }
        raw_limits = detail.get("limits") if isinstance(detail, dict) else None
        if not isinstance(raw_limits, dict):
            return self._unusable_result()
        limits = {
            key: value
            for key, value in raw_limits.items()
            if key in recognized and type(value) is int and 0 < value <= 2**31 - 1
        }
        if not limits:
            return self._unusable_result()
        return TranslationError(
            413, "WORK_LIMIT_EXCEEDED", "Text exceeds the translation work budget.", limits=limits
        )
