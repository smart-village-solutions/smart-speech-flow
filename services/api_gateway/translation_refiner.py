import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock
from typing import Any, Dict, Optional

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

# Languages listed as supported by the Phi-4-mini-instruct model card.  Phi is
# still used as a target-language editor, so an unsupported source language is
# deliberately not a reason to skip refinement; it merely withholds the source
# text as an unreliable semantic reference.
_PHI4_MINI_SUPPORTED_LANGUAGE_CODES = frozenset(
    {
        "ar",
        "cs",
        "da",
        "de",
        "en",
        "es",
        "fi",
        "fr",
        "he",
        "hu",
        "it",
        "ja",
        "ko",
        "nl",
        "no",
        "pl",
        "pt",
        "ru",
        "sv",
        "th",
        "tr",
        "uk",
        "zh",
    }
)


def _language_code_is_supported_by_phi4_mini(language_code: str) -> bool:
    """Return whether a language code is covered by Phi-4-mini's model card."""
    normalized_code = language_code.strip().lower().split("-", maxsplit=1)[0]
    return normalized_code in _PHI4_MINI_SUPPORTED_LANGUAGE_CODES


def _is_phi4_mini_model(model: str) -> bool:
    return model.strip().lower().startswith("phi4-mini")


def _default_refinement_endpoint() -> str:
    scheme = os.getenv("LLM_REFINEMENT_SCHEME", "http")
    host = os.getenv("LLM_REFINEMENT_HOST", "ollama")
    port = os.getenv("LLM_REFINEMENT_PORT", "11434")
    return f"{scheme}://{host}:{port}"


def _strtobool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


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


_CANDIDATE_EXECUTOR = ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="refinement-shadow"
)


class BaseTranslationRefiner:
    """Base class for optional translation refinement."""

    is_active: bool = False

    #: Set by the gateway's lifespan. None means telemetry is not wired up,
    #: which must be indistinguishable from telemetry being switched off.
    quality_telemetry: Optional[Any] = None

    def attach_quality_telemetry(self, telemetry: Optional[Any]) -> None:
        self.quality_telemetry = telemetry

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
        """Record one attempt. Never allowed to affect the caller."""
        telemetry = self.quality_telemetry
        if telemetry is None:
            return
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

    def _emit_outcome(
        self,
        outcome: "RefinementOutcome",
        *,
        role: "RefinerRole",
        model_ref: str,
        source_lang: str,
        target_lang: str,
    ) -> None:
        failed = bool(outcome.error)
        self._emit_attempt(
            role=role,
            model_ref=model_ref,
            outcome=(
                RefinementOutcomeCode.ERROR if failed else RefinementOutcomeCode.SUCCESS
            ),
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
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.max_retries = max(1, max_retries)
        self.think = think
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
        if original_text and (
            not _is_phi4_mini_model(self.model)
            or _language_code_is_supported_by_phi4_mini(source_lang)
        ):
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

        if _is_phi4_mini_model(
            self.model
        ) and not _language_code_is_supported_by_phi4_mini(target_lang):
            logger.info(
                "Skipping Phi-4-mini refinement for unsupported target language '%s'",
                target_lang,
            )
            return RefinementOutcome(
                text=text, changed=False, latency_ms=0.0, error=None, model=self.model
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
                refined = (data.get("response") or "").strip()

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


class ShadowComparisonRefiner(OllamaTranslationRefiner):
    """Executes the primary model in-path and a bounded candidate job in background."""

    def __init__(
        self, *args: Any, candidate_model: str, queue_limit: int, **kwargs: Any
    ) -> None:
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
                self._emit_candidate_not_run(
                    RefinementOutcomeCode.SKIPPED_OVERLOAD, args, kwargs
                )
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
            self._emit_candidate_not_run(
                RefinementOutcomeCode.SUBMISSION_FAILED, args, kwargs
            )
        return outcome


def get_translation_refiner() -> BaseTranslationRefiner:
    mode = os.getenv("LLM_REFINEMENT_MODE", "").strip().lower()
    enabled = _strtobool(os.getenv("LLM_REFINEMENT_ENABLED", "false"))
    mode = mode or ("primary_only" if enabled else "disabled")
    if mode not in {"disabled", "primary_only", "candidate_only", "shadow_compare"}:
        raise ValueError("Invalid LLM_REFINEMENT_MODE")
    if mode == "disabled":
        logger.info("LLM translation refinement disabled")
        return NoOpTranslationRefiner()

    endpoint = os.getenv("LLM_REFINEMENT_ENDPOINT", _default_refinement_endpoint())
    primary_model = os.getenv(
        "LLM_REFINEMENT_PRIMARY_MODEL", os.getenv("LLM_REFINEMENT_MODEL", "gpt-oss:20b")
    )
    candidate_model = os.getenv("LLM_REFINEMENT_CANDIDATE_MODEL", "phi4-mini")
    model = candidate_model if mode == "candidate_only" else primary_model
    timeout_seconds = float(os.getenv("LLM_REFINEMENT_TIMEOUT", "4.0"))
    if not 3.0 <= timeout_seconds <= 5.0:
        raise ValueError("LLM_REFINEMENT_TIMEOUT must be between 3.0 and 5.0")
    temperature = float(os.getenv("LLM_REFINEMENT_TEMPERATURE", "0.7"))
    max_retries = int(os.getenv("LLM_REFINEMENT_MAX_RETRIES", "1"))
    think = _strtobool(os.getenv("LLM_REFINEMENT_THINK", "false"))

    logger.info(
        "LLM translation refinement enabled with model '%s' at %s", model, endpoint
    )
    args = {
        "endpoint": endpoint,
        "model": model,
        "timeout_seconds": timeout_seconds,
        "temperature": temperature,
        "max_retries": max_retries,
        "think": think,
    }
    if mode == "shadow_compare":
        return ShadowComparisonRefiner(
            **args,
            candidate_model=candidate_model,
            queue_limit=int(os.getenv("LLM_REFINEMENT_SHADOW_QUEUE_LIMIT", "4")),
        )
    return OllamaTranslationRefiner(**args)


translation_refiner: BaseTranslationRefiner = get_translation_refiner()

__all__ = [
    "RefinementOutcome",
    "BaseTranslationRefiner",
    "NoOpTranslationRefiner",
    "OllamaTranslationRefiner",
    "ShadowComparisonRefiner",
    "get_translation_refiner",
    "translation_refiner",
]
