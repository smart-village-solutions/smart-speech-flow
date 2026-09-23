import importlib
import os
from unittest.mock import ANY, Mock

import pytest

MODULE_PATH = "services.api_gateway.translation_refiner"


def reload_module(env: dict[str, str | None]):
    """Reload translation refiner module with temporary env overrides."""
    saved: dict[str, str | None] = {}
    for key, value in env.items():
        saved[key] = os.environ.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    try:
        module = importlib.import_module(MODULE_PATH)
        return importlib.reload(module)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_translation_refiner_disabled_returns_noop(monkeypatch):
    mod = reload_module({
        "LLM_REFINEMENT_ENABLED": "0",
        "LLM_REFINEMENT_ENDPOINT": None,
    })
    outcome = mod.translation_refiner.refine("Hallo", "de", "en", context=None)
    assert outcome.text == "Hallo"
    assert outcome.changed is False
    assert mod.translation_refiner.is_active is False


def test_translation_refiner_handles_errors(monkeypatch):
    mod = reload_module({
        "LLM_REFINEMENT_ENABLED": "1",
        "LLM_REFINEMENT_ENDPOINT": "http://ollama:11434",
    })

    def fake_post(*args, **kwargs):  # noqa: ANN001, D401
        raise ConnectionError("unreachable")

    monkeypatch.setattr(mod.requests, "post", fake_post)

    outcome = mod.translation_refiner.refine("Hallo", "de", "en", context=None)
    assert outcome.text == "Hallo"
    assert outcome.changed is False
    assert outcome.error is not None

    # restore default module state for other tests
    reload_module({"LLM_REFINEMENT_ENABLED": "0"})


def test_ollama_translation_refiner_returns_refined_text(monkeypatch):
    mod = reload_module({"LLM_REFINEMENT_ENABLED": "0"})
    response = Mock()
    response.json.return_value = {"response": "  Hello, world!  "}
    monkeypatch.setattr(mod.requests, "post", Mock(return_value=response))

    refiner = mod.OllamaTranslationRefiner(
        endpoint="http://ollama:11434/",
        model="phi4-mini",
        timeout_seconds=1.0,
        temperature=0.2,
        max_retries=1,
    )

    outcome = refiner.refine(
        "Hallo Welt",
        "de",
        "en",
        context={"original_text": "Hallo Welt"},
    )

    assert outcome.text == "Hello, world!"
    assert outcome.changed is True
    assert outcome.error is None
    assert outcome.model == "phi4-mini"
    response.raise_for_status.assert_called_once()
    mod.requests.post.assert_called_once_with(
        "http://ollama:11434/api/generate",
        json={
            "model": "phi4-mini",
            "prompt": ANY,
            "stream": False,
            "think": False,
            "options": {"temperature": 0.2},
        },
        timeout=1.0,
    )


def test_prompt_uses_source_as_meaning_anchor_for_a_language_outside_the_skip_list():
    mod = reload_module({"LLM_REFINEMENT_ENABLED": "0"})
    refiner = mod.OllamaTranslationRefiner(
        endpoint="http://ollama:11434",
        model="phi4-mini",
        timeout_seconds=1.0,
        temperature=0.2,
        max_retries=1,
        skip_target_languages=["ti", "ku"],
    )

    prompt = refiner._build_prompt(
        "Hello", "de", "en", context={"original_text": "Hallo"}
    )

    assert "Original user input: Hallo" in prompt
    assert "Use the original input only to verify" in prompt


def test_prompt_omits_source_text_for_a_language_inside_the_skip_list():
    mod = reload_module({"LLM_REFINEMENT_ENABLED": "0"})
    refiner = mod.OllamaTranslationRefiner(
        endpoint="http://ollama:11434",
        model="phi4-mini",
        timeout_seconds=1.0,
        temperature=0.2,
        max_retries=1,
        skip_target_languages=["ti", "ku"],
    )

    prompt = refiner._build_prompt(
        "Hello", "ti", "en", context={"original_text": "\u12a8\u1218\u12ed"}
    )

    assert "Original user input:" not in prompt
    assert "\u12a8\u1218\u12ed" not in prompt


def test_skips_refinement_for_a_configured_target_language(monkeypatch):
    mod = reload_module({"LLM_REFINEMENT_ENABLED": "0"})
    post = Mock()
    monkeypatch.setattr(mod.requests, "post", post)
    refiner = mod.OllamaTranslationRefiner(
        endpoint="http://ollama:11434",
        model="phi4-mini",
        timeout_seconds=1.0,
        temperature=0.2,
        max_retries=1,
        skip_target_languages=["am", "ti", "ku", "fa"],
    )

    outcome = refiner.refine("\u12a8\u1218\u12ed", "de", "ti")

    assert outcome.text == "\u12a8\u1218\u12ed"
    assert outcome.changed is False
    assert outcome.latency_ms == 0.0
    post.assert_not_called()


def test_skips_a_configured_target_language(monkeypatch):
    mod = reload_module({"LLM_REFINEMENT_ENABLED": "0"})
    refiner = mod.OllamaTranslationRefiner(
        endpoint="http://vllm:8000",
        model="gemma-4-e4b-qat",
        timeout_seconds=4.0,
        temperature=0.7,
        max_retries=1,
        skip_target_languages=["am", "ti"],
    )
    monkeypatch.setattr(
        refiner, "_request", lambda prompt: pytest.fail("no request may be sent")
    )

    outcome = refiner._perform_refinement("selam", "de", "am")

    assert outcome.text == "selam"
    assert outcome.changed is False
    assert outcome.skipped_reason == "unsupported_target_language"


def test_refines_a_language_outside_the_skip_list(monkeypatch):
    mod = reload_module({"LLM_REFINEMENT_ENABLED": "0"})
    response = Mock()
    response.json.return_value = {"response": "Guten Tag."}
    monkeypatch.setattr(mod.requests, "post", Mock(return_value=response))
    refiner = mod.OllamaTranslationRefiner(
        endpoint="http://vllm:8000",
        model="gemma-4-e4b-qat",
        timeout_seconds=4.0,
        temperature=0.7,
        max_retries=1,
        skip_target_languages=["am"],
    )

    outcome = refiner._perform_refinement("Guten tag", "ar", "de")

    assert outcome.text == "Guten Tag."
    assert outcome.skipped_reason is None


def test_a_skipped_refinement_is_emitted_as_skipped(monkeypatch):
    """A skip that reads as a success hides exactly the decision we made."""
    mod = reload_module({"LLM_REFINEMENT_ENABLED": "0"})
    emitted = []
    refiner = mod.OllamaTranslationRefiner(
        endpoint="http://vllm:8000",
        model="gemma-4-e4b-qat",
        timeout_seconds=4.0,
        temperature=0.7,
        max_retries=1,
        skip_target_languages=["fa"],
    )
    monkeypatch.setattr(refiner, "_emit_attempt", lambda **kwargs: emitted.append(kwargs))

    refiner.refine("salam", "de", "fa")

    assert emitted[0]["outcome"] is mod.RefinementOutcomeCode.SKIPPED_LANGUAGE


def test_shadow_comparison_refiner_schedules_candidate(monkeypatch):
    mod = reload_module({"LLM_REFINEMENT_ENABLED": "0"})
    refiner = mod.ShadowComparisonRefiner(
        endpoint="http://ollama:11434",
        model="primary",
        candidate_model="candidate",
        queue_limit=1,
        timeout_seconds=1.0,
        temperature=0.2,
        max_retries=1,
    )
    monkeypatch.setattr(
        mod.OllamaTranslationRefiner,
        "refine",
        Mock(return_value=mod.RefinementOutcome(text="refined", changed=True)),
    )
    submit = Mock()
    monkeypatch.setattr(mod._CANDIDATE_EXECUTOR, "submit", submit)

    outcome = refiner.refine("Hallo", "de", "en")

    assert outcome.candidate_model == "candidate"
    assert outcome.candidate_status == "scheduled"
    assert refiner.pending == 1
    submit.assert_called_once()


def test_shadow_comparison_refiner_records_candidate_result(monkeypatch):
    mod = reload_module({"LLM_REFINEMENT_ENABLED": "0"})
    refiner = mod.ShadowComparisonRefiner(
        endpoint="http://ollama:11434",
        model="primary",
        candidate_model="candidate",
        queue_limit=1,
        timeout_seconds=1.0,
        temperature=0.2,
        max_retries=1,
    )
    refiner.pending = 1
    monkeypatch.setattr(
        mod.OllamaTranslationRefiner,
        "refine",
        Mock(return_value=mod.RefinementOutcome(text="refined", changed=True)),
    )

    refiner._run_candidate("Hallo", "de", "en")

    assert refiner.pending == 0


def test_shadow_comparison_candidate_skips_a_configured_target_language(monkeypatch):
    """The candidate must inherit the primary's skip list, not decide on its own.

    Drives the actual code path `_run_candidate` takes
    (`candidate._perform_refinement`, not the mocked `refine`), so this fails
    if `skip_target_languages` is ever dropped from the candidate's
    construction in `_run_candidate`.
    """
    mod = reload_module({"LLM_REFINEMENT_ENABLED": "0"})
    refiner = mod.ShadowComparisonRefiner(
        endpoint="http://ollama:11434",
        model="primary",
        candidate_model="candidate",
        queue_limit=1,
        timeout_seconds=1.0,
        temperature=0.2,
        max_retries=1,
        skip_target_languages=["ti"],
    )
    refiner.pending = 1
    post = Mock()
    monkeypatch.setattr(mod.requests, "post", post)
    emitted = []
    monkeypatch.setattr(refiner, "_emit_attempt", lambda **kwargs: emitted.append(kwargs))

    refiner._run_candidate("ከመይ", "de", "ti")

    post.assert_not_called()
    assert emitted[0]["outcome"] is mod.RefinementOutcomeCode.SKIPPED_LANGUAGE
    assert emitted[0]["role"] is mod.RefinerRole.CANDIDATE


def test_shadow_comparison_refiner_recovers_when_submission_fails(monkeypatch):
    mod = reload_module({"LLM_REFINEMENT_ENABLED": "0"})
    refiner = mod.ShadowComparisonRefiner(
        endpoint="http://ollama:11434",
        model="primary",
        candidate_model="candidate",
        queue_limit=1,
        timeout_seconds=1.0,
        temperature=0.2,
        max_retries=1,
    )
    monkeypatch.setattr(
        mod.OllamaTranslationRefiner,
        "refine",
        Mock(return_value=mod.RefinementOutcome(text="refined", changed=True)),
    )
    monkeypatch.setattr(
        mod._CANDIDATE_EXECUTOR,
        "submit",
        Mock(side_effect=RuntimeError("executor shut down")),
    )

    outcome = refiner.refine("Hallo", "de", "en")

    assert outcome.candidate_status == "submission_failed"
    assert refiner.pending == 0
