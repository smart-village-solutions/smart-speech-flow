import logging
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlparse

import requests
from requests import Response, exceptions

from .quality_telemetry import (
    QualityErrorCode,
    RefinementOutcomeCode,
    RefinerRole,
    classify_exception,
    classify_upstream_status,
)

logger = logging.getLogger(__name__)

DEFAULT_SKIP_TARGET_LANGUAGES = "am,ti,ku,fa"


def _normalized_language(code: str) -> str:
    return code.strip().lower().split("-", maxsplit=1)[0]


def _skip_target_languages() -> frozenset[str]:
    """Target languages the refiner leaves untouched.

    The default is the four supported languages Phi-4-mini's model card does
    not cover, which keeps behaviour identical to the model-name check this
    replaces. Which languages get refined is a product decision, so it belongs
    in configuration rather than in a check on the model's name.
    """
    raw = os.getenv("LLM_REFINEMENT_SKIP_TARGET_LANGUAGES", DEFAULT_SKIP_TARGET_LANGUAGES)
    return frozenset(_normalized_language(code) for code in raw.split(",") if code.strip())


REFINEMENT_BACKENDS = ("ollama", "vllm")
_BACKEND_DEFAULT_ENDPOINTS = {
    "ollama": ("ollama", "11434"),
    "vllm": ("vllm", "8000"),
}


def _resolve_refinement_backend() -> str:
    raw = os.getenv("LLM_REFINEMENT_BACKEND", "ollama")
    backend = raw.strip().lower() or "ollama"
    if backend not in REFINEMENT_BACKENDS:
        raise ValueError(
            f"LLM_REFINEMENT_BACKEND={raw!r} is not supported; "
            f"use one of {', '.join(REFINEMENT_BACKENDS)}"
        )
    return backend


def _default_refinement_endpoint(backend: str) -> str:
    default_host, default_port = _BACKEND_DEFAULT_ENDPOINTS[backend]
    scheme = os.getenv("LLM_REFINEMENT_SCHEME", "http")
    host = os.getenv("LLM_REFINEMENT_HOST", default_host)
    port = os.getenv("LLM_REFINEMENT_PORT", default_port)
    return f"{scheme}://{host}:{port}"


_BACKEND_DEFAULT_MODELS = {
    "ollama": "gpt-oss:20b",
    "vllm": "qwen3.5-4b",
}


def _default_refinement_model(backend: str) -> str:
    """The model a backend serves when no model variable is set.

    Mirrors `_default_refinement_endpoint`: the vllm service's
    --served-model-name defaults to the same "qwen3.5-4b" string, so an
    unset LLM_REFINEMENT_PRIMARY_MODEL resolves to a model vLLM actually
    advertises instead of the Ollama-only "gpt-oss:20b" default.
    """
    return _BACKEND_DEFAULT_MODELS[backend]


def _looks_like_ollama_endpoint(endpoint: str) -> bool:
    parsed = urlparse(endpoint)
    return parsed.hostname == "ollama" or parsed.port == 11434


def _warn_if_endpoint_pins_ollama(backend: str, explicit_endpoint: str) -> None:
    """An explicit LLM_REFINEMENT_ENDPOINT silently overrides the backend switch.

    Ollama also serves `/v1/chat/completions`, so a deployment that flips
    LLM_REFINEMENT_BACKEND to vllm while an old Ollama endpoint lingers in
    LLM_REFINEMENT_ENDPOINT keeps sending every request to Ollama and appears
    to work. This only warns, never refuses: a vLLM instance deliberately
    proxied through host `ollama` or port 11434 is a valid setup.
    """
    if backend == "vllm" and _looks_like_ollama_endpoint(explicit_endpoint):
        logger.warning(
            "LLM_REFINEMENT_BACKEND=vllm but LLM_REFINEMENT_ENDPOINT=%s looks "
            "like an Ollama endpoint; refinement requests may be reaching "
            "Ollama instead of vLLM",
            explicit_endpoint,
        )


_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})
REFINEMENT_MODES = ("disabled", "primary_only", "candidate_only", "shadow_compare")


def _env_flag(name: str) -> Optional[bool]:
    """Unset or empty is None; anything unrecognised fails startup.

    A typo in a kill switch must never be read as a value -- that is how
    `LLM_REFINEMENT_ENABLED=flase` would silently keep refinement on.
    """
    raw = os.getenv(name, "")
    value = raw.strip().lower()
    if not value:
        return None
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise ValueError(f"{name}={raw!r} is not a boolean; use true/false, 1/0, yes/no or on/off")


def _env_number(
    name: str,
    default: str,
    parse: Any,
    minimum: float,
    maximum: Optional[float] = None,
) -> Any:
    raw = os.getenv(name, default)
    bounds = f"between {minimum} and {maximum}" if maximum is not None else f"at least {minimum}"
    try:
        value = parse(raw.strip())
    except ValueError:
        raise ValueError(f"{name}={raw!r} is not a number; it must be {bounds}") from None
    if not math.isfinite(value) or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{name}={raw!r} is out of range; it must be {bounds}")
    return value


def _resolve_refinement_mode() -> str:
    """ENABLED=false wins over any mode; otherwise an explicit mode wins."""
    enabled = _env_flag("LLM_REFINEMENT_ENABLED")
    raw_mode = os.getenv("LLM_REFINEMENT_MODE", "")
    mode = raw_mode.strip().lower()
    if enabled is False:
        if mode and mode != "disabled":
            logger.warning(
                "LLM_REFINEMENT_ENABLED=false overrides LLM_REFINEMENT_MODE=%s; "
                "refinement is disabled",
                mode,
            )
        return "disabled"
    mode = mode or ("primary_only" if enabled else "disabled")
    if mode not in REFINEMENT_MODES:
        raise ValueError(
            f"LLM_REFINEMENT_MODE={raw_mode!r} is not supported; "
            f"use one of {', '.join(REFINEMENT_MODES)}"
        )
    return mode


def _classify_refinement_failure(exc: BaseException) -> QualityErrorCode:
    """Classify at the catch site, where the exception class still exists.

    `error` is a string by the time anything downstream sees it, and
    `classify_exception(RuntimeError(message))` cannot recover the class -- it
    matches on the MRO, and RuntimeError's MRO intersects none of the name sets,
    so every failure would collapse to `internal_error`.

    requests raises one class, HTTPError, for every non-2xx status, so a status
    is read from the response in preference to the class.
    """
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(status, int):
        return classify_upstream_status(status)
    return classify_exception(exc)


@dataclass
class RefinementOutcome:
    text: str
    changed: bool
    latency_ms: Optional[float] = None
    error: Optional[str] = None
    error_code: QualityErrorCode = QualityErrorCode.NONE
    raw_response: Optional[Dict[str, Any]] = None
    model: Optional[str] = None
    candidate_model: Optional[str] = None
    candidate_status: Optional[str] = None
    skipped_reason: Optional[str] = None


_CANDIDATE_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="refinement-shadow")


class BaseTranslationRefiner:
    """Base class for optional translation refinement."""

    is_active: bool = False

    #: Set by the gateway's lifespan. None means telemetry is not wired up,
    #: which must be indistinguishable from telemetry being switched off.
    quality_telemetry: Optional[Any] = None

    #: Set by the gateway the same way as `quality_telemetry`. None means the
    #: counters are not wired up, which must never change an outcome.
    refinement_metrics: Optional[Any] = None

    def attach_quality_telemetry(self, telemetry: Optional[Any]) -> None:
        self.quality_telemetry = telemetry

    def attach_refinement_metrics(self, metrics: Optional[Any]) -> None:
        self.refinement_metrics = metrics

    def _emit_attempt(
        self,
        *,
        role: "RefinerRole",
        model_ref: str,
        outcome: "RefinementOutcomeCode",
        latency_ms: int,
        changed: bool,
        source_lang: str,
        target_lang: str,
        error_code: "QualityErrorCode",
    ) -> None:
        """Record one attempt. Never allowed to affect the caller.

        This is the single choke point every emitted attempt passes through
        -- including `_emit_candidate_not_run`'s SKIPPED_OVERLOAD and
        SUBMISSION_FAILED codes, which never go through `_emit_outcome`.
        Recording the counter here, rather than in `_emit_outcome`, is what
        keeps telemetry and the counter from disagreeing about which
        outcomes were counted.
        """
        telemetry = self.quality_telemetry
        if telemetry is not None:
            try:
                telemetry.emit_refinement_attempt(
                    refiner_role=role,
                    model_ref=model_ref,
                    outcome=outcome,
                    latency_ms=latency_ms,
                    changed=changed,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    error_code=error_code,
                )
            except Exception:  # telemetry must never change an outcome
                logger.warning("Quality telemetry emit failed for a refinement attempt")

        metrics = self.refinement_metrics
        if metrics is not None:
            try:
                metrics.record(outcome.value, model_ref)
            except Exception:  # metrics must never change an outcome
                logger.warning("Refinement metrics update failed")

    def _emit_outcome(
        self,
        outcome: "RefinementOutcome",
        *,
        role: "RefinerRole",
        model_ref: str,
        source_lang: str,
        target_lang: str,
    ) -> None:
        if outcome.skipped_reason:
            code = RefinementOutcomeCode.SKIPPED_LANGUAGE
        elif outcome.error:
            code = RefinementOutcomeCode.ERROR
        else:
            code = RefinementOutcomeCode.SUCCESS
        self._emit_attempt(
            role=role,
            model_ref=model_ref,
            outcome=code,
            latency_ms=int(outcome.latency_ms or 0),
            changed=bool(outcome.changed),
            source_lang=source_lang,
            target_lang=target_lang,
            error_code=outcome.error_code,
        )

    def refine(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> RefinementOutcome:
        raise NotImplementedError


class NoOpTranslationRefiner(BaseTranslationRefiner):
    """Default implementation that returns text unchanged."""

    def refine(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> RefinementOutcome:
        return RefinementOutcome(text=text, changed=False, latency_ms=0.0, error=None)


class OllamaTranslationRefiner(BaseTranslationRefiner):
    """Refines translation output using a locally hosted Ollama model."""

    def __init__(
        self,
        endpoint: str,
        model: str,
        timeout_seconds: float,
        temperature: float,
        max_retries: int,
        think: bool = False,
        skip_target_languages: Optional[Iterable[str]] = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.max_retries = max(1, max_retries)
        self.think = think
        self.skip_target_languages = frozenset(
            _normalized_language(code) for code in (skip_target_languages or ())
        )
        self.is_active = True

    def _build_prompt(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        original_text = context.get("original_text") if context else None
        prompt = (
            "You improve a translation for a spoken conversation.\n"
            "Return only the improved translation in the target language.\n"
            "Preserve the original meaning, intent, tone, level of formality, names, "
            "numbers, dates, units, and technical terms. Do not add, omit, summarize, "
            "or explain anything. Make only changes that improve grammatical correctness, "
            "fluency, and naturalness for speech. If the candidate is already good, "
            "return it unchanged."
        )
        if source_lang:
            prompt += f"\nOriginal language code: {source_lang}."
        if target_lang:
            prompt += f"\nTarget language code: {target_lang}."
        if original_text and _normalized_language(source_lang) not in self.skip_target_languages:
            prompt += (
                "\nUse the original input only to verify that meaning is preserved. "
                "Do not translate again unless the current translation contains a clear error."
            )
            prompt += f"\nOriginal user input: {original_text}"
        prompt += f"\nCurrent translation candidate: {text}\nImproved translation:"
        return prompt

    def _request(self, prompt: str) -> Response:
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "think": self.think,
            "options": {"temperature": self.temperature},
        }
        url = f"{self.endpoint}/api/generate"
        return requests.post(url, json=payload, timeout=self.timeout_seconds)

    def _extract_text(self, data: Dict[str, Any]) -> str:
        """The generated text, by this backend's response shape."""
        return (data.get("response") or "").strip()

    def refine(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> RefinementOutcome:
        """Refine in-path, recording the attempt.

        The emit lives here rather than in the shadow subclass because
        production runs `primary_only`: an event reachable only from the shadow
        candidate is an event production never produces, and a dashboard that
        is empty exactly where it matters.
        """
        outcome = self._perform_refinement(text, source_lang, target_lang, context)
        self._emit_outcome(
            outcome,
            role=RefinerRole.PRIMARY,
            model_ref=self.model,
            source_lang=source_lang,
            target_lang=target_lang,
        )
        return outcome

    def _perform_refinement(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> RefinementOutcome:
        if not text:
            return RefinementOutcome(
                text=text, changed=False, latency_ms=0.0, error=None, model=self.model
            )

        if _normalized_language(target_lang) in self.skip_target_languages:
            logger.info("Skipping refinement for unsupported target language '%s'", target_lang)
            return RefinementOutcome(
                text=text,
                changed=False,
                latency_ms=0.0,
                error=None,
                model=self.model,
                skipped_reason="unsupported_target_language",
            )

        prompt = self._build_prompt(text, source_lang, target_lang, context)
        start_time = time.perf_counter()

        last_error: Optional[str] = None
        last_error_code = QualityErrorCode.UNKNOWN
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self._request(prompt)
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                response.raise_for_status()
                data = response.json()
                refined = self._extract_text(data)

                if not refined:
                    return RefinementOutcome(
                        text=text,
                        changed=False,
                        latency_ms=elapsed_ms,
                        error="empty_response",
                        error_code=QualityErrorCode.UPSTREAM_MALFORMED_RESPONSE,
                        raw_response=data,
                        model=self.model,
                    )

                changed = refined != text
                return RefinementOutcome(
                    text=refined,
                    changed=changed,
                    latency_ms=elapsed_ms,
                    error=None,
                    raw_response=data,
                    model=self.model,
                )
            except exceptions.Timeout as exc:
                last_error = str(exc)
                last_error_code = QualityErrorCode.UPSTREAM_TIMEOUT
                if attempt < self.max_retries:
                    logger.warning(
                        "Translation refinement timeout (attempt %s/%s), retrying...",
                        attempt,
                        self.max_retries,
                    )
                    time.sleep(min(0.1 * (2 ** (attempt - 1)), 1.0))
                    continue
                logger.warning("Translation refinement failed after retries: %s", exc)
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                last_error_code = _classify_refinement_failure(exc)
                logger.warning("Translation refinement failed: %s", exc)
                break

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return RefinementOutcome(
            text=text,
            changed=False,
            latency_ms=elapsed_ms,
            error=last_error,
            error_code=last_error_code,
            raw_response=None,
            model=self.model,
        )


class VllmTranslationRefiner(OllamaTranslationRefiner):
    """Refines translation output through vLLM's OpenAI-compatible API.

    Retry, timeout, telemetry and the language policy are inherited; only the
    request shape and the response shape differ.
    """

    def __init__(
        self,
        endpoint: str,
        model: str,
        timeout_seconds: float,
        temperature: float,
        max_retries: int,
        think: bool = False,
        skip_target_languages: Optional[Iterable[str]] = None,
        max_tokens: int = 256,
    ) -> None:
        super().__init__(
            endpoint,
            model,
            timeout_seconds,
            temperature,
            max_retries,
            think,
            skip_target_languages,
        )
        self.max_tokens = max_tokens

    def _request(self, prompt: str) -> Response:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            # Deliberation inside a 4 s budget is what made gpt-oss:20b
            # unusable; models that reason by default must be told not to.
            "chat_template_kwargs": {"enable_thinking": self.think},
        }
        url = f"{self.endpoint}/v1/chat/completions"
        return requests.post(url, json=payload, timeout=self.timeout_seconds)

    def _extract_text(self, data: Dict[str, Any]) -> str:
        choices = data.get("choices") or []
        if not choices:
            return ""
        choice = choices[0]
        message = choice.get("message") or {}
        text = (message.get("content") or "").strip()
        if choice.get("finish_reason") == "length":
            # A response cut off at the token cap is worse than no refinement:
            # it replaces a complete translation with a sentence fragment that
            # then gets spoken aloud by TTS. Returning "" here routes through
            # the same empty-response branch in `_perform_refinement`, which
            # already keeps the original translation and records an error.
            logger.warning(
                "Translation refinement response truncated at max_tokens=%s; "
                "discarding and keeping the original translation",
                self.max_tokens,
            )
            return ""
        return text


class ShadowComparisonRefiner(OllamaTranslationRefiner):
    """Executes the primary model in-path and a bounded candidate job in background."""

    def __init__(self, *args: Any, candidate_model: str, queue_limit: int, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.candidate_model = candidate_model
        self.queue_limit = max(1, queue_limit)
        self.pending = 0
        self.lock = Lock()

    @staticmethod
    def _requested_languages(args: Any, kwargs: Any) -> tuple[str, str]:
        """`refine(text, source_lang, target_lang, context=None)`, called either
        way round by the two pipelines."""
        source = kwargs.get("source_lang") or (args[1] if len(args) > 1 else "")
        target = kwargs.get("target_lang") or (args[2] if len(args) > 2 else "")
        return str(source), str(target)

    def _run_candidate(self, *args: Any, **kwargs: Any) -> None:
        try:
            candidate = OllamaTranslationRefiner(
                self.endpoint,
                self.candidate_model,
                self.timeout_seconds,
                self.temperature,
                self.max_retries,
                self.think,
                skip_target_languages=self.skip_target_languages,
            )
            # _perform_refinement, not refine: the latter would emit this as a
            # PRIMARY attempt under the candidate's model name.
            result = candidate._perform_refinement(*args, **kwargs)
            status = "error" if result.error else "success"
            logger.info(
                "Shadow candidate model=%s status=%s latency_ms=%s",
                self.candidate_model,
                status,
                result.latency_ms,
            )
            source_lang, target_lang = self._requested_languages(args, kwargs)
            # The candidate's latency has always been measured here and thrown
            # away into that log line. The refinement benchmarking work asks
            # exactly this question and has had no data for it.
            self._emit_outcome(
                result,
                role=RefinerRole.CANDIDATE,
                model_ref=self.candidate_model,
                source_lang=source_lang,
                target_lang=target_lang,
            )
        finally:
            with self.lock:
                self.pending -= 1

    def _emit_candidate_not_run(
        self, outcome_code: RefinementOutcomeCode, args: Any, kwargs: Any
    ) -> None:
        """A candidate that never ran is still an attempt worth counting.

        Without this, shadow-queue overload is invisible: the run produces no
        row, so the dashboard shows a lower attempt count rather than a
        saturated queue, and SKIPPED_OVERLOAD and SUBMISSION_FAILED are
        unreachable enum values.
        """
        source_lang, target_lang = self._requested_languages(args, kwargs)
        self._emit_attempt(
            role=RefinerRole.CANDIDATE,
            model_ref=self.candidate_model,
            outcome=outcome_code,
            latency_ms=0,
            changed=False,
            source_lang=source_lang,
            target_lang=target_lang,
            error_code=QualityErrorCode.REFINEMENT_OVERLOADED,
        )

    def refine(self, *args: Any, **kwargs: Any) -> RefinementOutcome:
        outcome = super().refine(*args, **kwargs)
        outcome.candidate_model = self.candidate_model
        with self.lock:
            if self.pending >= self.queue_limit:
                outcome.candidate_status = "skipped_overload"
                self._emit_candidate_not_run(RefinementOutcomeCode.SKIPPED_OVERLOAD, args, kwargs)
                return outcome
            self.pending += 1
        outcome.candidate_status = "scheduled"
        try:
            _CANDIDATE_EXECUTOR.submit(self._run_candidate, *args, **kwargs)
        except RuntimeError:
            with self.lock:
                self.pending -= 1
            outcome.candidate_status = "submission_failed"
            logger.warning("Unable to schedule shadow candidate refinement")
            self._emit_candidate_not_run(RefinementOutcomeCode.SUBMISSION_FAILED, args, kwargs)
        return outcome


def get_translation_refiner() -> BaseTranslationRefiner:
    mode = _resolve_refinement_mode()
    if mode == "disabled":
        logger.info("LLM translation refinement disabled")
        return NoOpTranslationRefiner()

    backend = _resolve_refinement_backend()
    if backend == "vllm" and mode in ("shadow_compare", "candidate_only"):
        raise ValueError(
            f"LLM_REFINEMENT_MODE={mode} is not supported on "
            f"LLM_REFINEMENT_BACKEND={backend}; the vllm service only serves "
            "LLM_REFINEMENT_PRIMARY_MODEL, not the candidate model this mode "
            "requires -- run it on ollama"
        )
    # Blank counts as unset, matching `_env_flag`: compose always sets this
    # variable (even to an empty default), so `os.getenv`'s own fallback
    # never fires and the backend-aware default below would otherwise be
    # unreachable.
    explicit_endpoint = os.getenv("LLM_REFINEMENT_ENDPOINT", "").strip()
    endpoint = explicit_endpoint or _default_refinement_endpoint(backend)
    if explicit_endpoint:
        _warn_if_endpoint_pins_ollama(backend, explicit_endpoint)
    # Blank counts as unset, matching the endpoint resolution above: compose
    # always sets these variables (even to an empty default), so `os.getenv`'s
    # own fallback never fires and the backend-aware default below would
    # otherwise be unreachable.
    explicit_primary_model = os.getenv("LLM_REFINEMENT_PRIMARY_MODEL", "").strip()
    explicit_legacy_model = os.getenv("LLM_REFINEMENT_MODEL", "").strip()
    primary_model = (
        explicit_primary_model or explicit_legacy_model or _default_refinement_model(backend)
    )
    candidate_model = os.getenv("LLM_REFINEMENT_CANDIDATE_MODEL", "phi4-mini")
    model = candidate_model if mode == "candidate_only" else primary_model
    timeout_seconds = _env_number("LLM_REFINEMENT_TIMEOUT", "4.0", float, 3.0, 5.0)
    # Refinement edits rather than composes, so zero temperature ensures deterministic,
    # reproducible output. Sampling temperature invites hallucinations that alter content.
    temperature = _env_number("LLM_REFINEMENT_TEMPERATURE", "0.0", float, 0.0)
    max_retries = _env_number("LLM_REFINEMENT_MAX_RETRIES", "1", int, 1)
    think = _env_flag("LLM_REFINEMENT_THINK") is True

    logger.info(
        "LLM translation refinement enabled with model '%s' at %s (backend=%s)",
        model,
        endpoint,
        backend,
    )
    args = {
        "endpoint": endpoint,
        "model": model,
        "timeout_seconds": timeout_seconds,
        "temperature": temperature,
        "max_retries": max_retries,
        "think": think,
        "skip_target_languages": _skip_target_languages(),
    }
    if mode == "shadow_compare":
        return ShadowComparisonRefiner(
            **args,
            candidate_model=candidate_model,
            queue_limit=_env_number("LLM_REFINEMENT_SHADOW_QUEUE_LIMIT", "4", int, 1),
        )
    if backend == "vllm":
        return VllmTranslationRefiner(
            **args,
            max_tokens=_env_number("LLM_REFINEMENT_MAX_TOKENS", "256", int, 16),
        )
    return OllamaTranslationRefiner(**args)


translation_refiner: BaseTranslationRefiner = get_translation_refiner()

__all__ = [
    "RefinementOutcome",
    "BaseTranslationRefiner",
    "NoOpTranslationRefiner",
    "OllamaTranslationRefiner",
    "VllmTranslationRefiner",
    "ShadowComparisonRefiner",
    "get_translation_refiner",
    "translation_refiner",
]
