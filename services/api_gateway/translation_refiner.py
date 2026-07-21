import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock
from typing import Any, Dict, Optional

import requests
from requests import Response, exceptions

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


@dataclass
class RefinementOutcome:
    text: str
    changed: bool
    latency_ms: Optional[float] = None
    error: Optional[str] = None
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
                logger.warning("Translation refinement failed: %s", exc)
                break

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return RefinementOutcome(
            text=text,
            changed=False,
            latency_ms=elapsed_ms,
            error=last_error,
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
            result = candidate.refine(*args, **kwargs)
            status = "error" if result.error else "success"
            logger.info(
                "Shadow candidate model=%s status=%s latency_ms=%s",
                self.candidate_model,
                status,
                result.latency_ms,
            )
        finally:
            with self.lock:
                self.pending -= 1

    def refine(self, *args: Any, **kwargs: Any) -> RefinementOutcome:
        outcome = super().refine(*args, **kwargs)
        outcome.candidate_model = self.candidate_model
        with self.lock:
            if self.pending >= self.queue_limit:
                outcome.candidate_status = "skipped_overload"
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
