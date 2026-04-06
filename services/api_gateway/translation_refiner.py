import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests
from requests import Response, exceptions

logger = logging.getLogger(__name__)


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
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.max_retries = max(1, max_retries)
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
            "You are an assistant that improves translation quality for spoken conversations. "
            "Polish the translated sentence so it sounds natural in the target language, but keep the original meaning. "
            "Respond with the improved sentence only."
        )
        if source_lang:
            prompt += f"\nOriginal language code: {source_lang}."
        if target_lang:
            prompt += f"\nTarget language code: {target_lang}."
        if original_text:
            prompt += f"\nOriginal user input: {original_text}"
        prompt += f"\nCurrent translation candidate: {text}\nImproved translation:"
        return prompt

    def _request(self, prompt: str) -> Response:
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
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
                text=text, changed=False, latency_ms=0.0, error=None
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
                    )

                changed = refined != text
                return RefinementOutcome(
                    text=refined,
                    changed=changed,
                    latency_ms=elapsed_ms,
                    error=None,
                    raw_response=data,
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
        )


def get_translation_refiner() -> BaseTranslationRefiner:
    enabled = _strtobool(os.getenv("LLM_REFINEMENT_ENABLED", "false"))
    if not enabled:
        logger.info("LLM translation refinement disabled")
        return NoOpTranslationRefiner()

    endpoint = os.getenv("LLM_REFINEMENT_ENDPOINT", _default_refinement_endpoint())
    model = os.getenv("LLM_REFINEMENT_MODEL", "gpt-oss:20b")
    timeout_seconds = float(os.getenv("LLM_REFINEMENT_TIMEOUT", "8.0"))
    temperature = float(os.getenv("LLM_REFINEMENT_TEMPERATURE", "0.7"))
    max_retries = int(os.getenv("LLM_REFINEMENT_MAX_RETRIES", "2"))

    logger.info(
        "LLM translation refinement enabled with model '%s' at %s", model, endpoint
    )
    return OllamaTranslationRefiner(
        endpoint=endpoint,
        model=model,
        timeout_seconds=timeout_seconds,
        temperature=temperature,
        max_retries=max_retries,
    )


translation_refiner: BaseTranslationRefiner = get_translation_refiner()

__all__ = [
    "RefinementOutcome",
    "BaseTranslationRefiner",
    "NoOpTranslationRefiner",
    "OllamaTranslationRefiner",
    "get_translation_refiner",
    "translation_refiner",
]
