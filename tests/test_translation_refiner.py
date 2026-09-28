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
    mod = importlib.import_module(MODULE_PATH)
    monkeypatch.setenv("LLM_REFINEMENT_ENABLED", "0")
    monkeypatch.delenv("LLM_REFINEMENT_ENDPOINT", raising=False)
    refiner = mod.get_translation_refiner()

    outcome = refiner.refine("Hallo", "de", "en", context=None)
    assert outcome.text == "Hallo"
    assert outcome.changed is False
    assert refiner.is_active is False


def test_translation_refiner_handles_errors(monkeypatch):
    mod = importlib.import_module(MODULE_PATH)
    monkeypatch.setenv("LLM_REFINEMENT_ENABLED", "1")
    monkeypatch.setenv("LLM_REFINEMENT_ENDPOINT", "http://ollama:11434")
    refiner = mod.get_translation_refiner()

    def fake_post(*args, **kwargs):  # noqa: ANN001, D401
        raise ConnectionError("unreachable")

    monkeypatch.setattr(mod.requests, "post", fake_post)

    outcome = refiner.refine("Hallo", "de", "en", context=None)
    assert outcome.text == "Hallo"
    assert outcome.changed is False
    assert outcome.error is not None


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


def test_prompt_forbids_substituting_a_synonym_for_the_candidate_s_own_terms():
    """Measured on the production model (2026-09-24, Qwen3.5-4B, 24 samples).

    The earlier wording asked only to "preserve technical terms" and lost 6 of
    24: `Personalausweis`/"identity card" came back as "passport" and
    `Buergeramt`/"citizens office" as "city hall" -- a mistranslation spoken
    aloud by TTS. Naming the substitution itself took that to 0 of 24 without
    leaving any of the 7 ungrammatical candidates uncorrected.
    """
    mod = reload_module({"LLM_REFINEMENT_ENABLED": "0"})
    refiner = mod.OllamaTranslationRefiner(
        endpoint="http://ollama:11434",
        model="phi4-mini",
        timeout_seconds=1.0,
        temperature=0.2,
        max_retries=1,
    )

    prompt = refiner._build_prompt("Hello", "de", "en")

    assert "a synonym is a mistranslation here" in prompt
    assert "Keep every word the candidate already uses" in prompt


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


def test_emit_outcome_records_the_same_code_sent_to_telemetry(monkeypatch):
    """The counter and the telemetry event must never disagree.

    Both are driven from the one call to `_emit_attempt` -- the single choke
    point every emitted attempt passes through -- so this asserts the
    telemetry emit and the metrics record receive exactly the same
    `RefinementOutcomeCode` value, and that each fires exactly once (a
    metrics call inside `_emit_outcome` as well as inside `_emit_attempt`
    would double-count every attempt).
    """
    mod = reload_module({"LLM_REFINEMENT_ENABLED": "0"})
    refiner = mod.NoOpTranslationRefiner()
    telemetry = Mock()
    refiner.quality_telemetry = telemetry
    refiner.refinement_metrics = Mock()

    refiner._emit_outcome(
        mod.RefinementOutcome(text="x", changed=False, error="boom"),
        role=mod.RefinerRole.PRIMARY,
        model_ref="gemma-4-e4b-qat",
        source_lang="de",
        target_lang="en",
    )

    telemetry.emit_refinement_attempt.assert_called_once()
    telemetry_outcome = telemetry.emit_refinement_attempt.call_args.kwargs["outcome"]
    assert telemetry_outcome is mod.RefinementOutcomeCode.ERROR

    refiner.refinement_metrics.record.assert_called_once_with("error", "gemma-4-e4b-qat")


def test_refinement_metrics_failure_never_changes_the_outcome(caplog):
    """Metrics recording is best-effort, exactly like the telemetry emit."""
    mod = reload_module({"LLM_REFINEMENT_ENABLED": "0"})
    refiner = mod.NoOpTranslationRefiner()

    def boom(outcome, model_ref):
        raise RuntimeError("registry is down")

    refiner.refinement_metrics = Mock(record=boom)

    with caplog.at_level("WARNING"):
        refiner._emit_outcome(
            mod.RefinementOutcome(text="x", changed=False, error=None),
            role=mod.RefinerRole.PRIMARY,
            model_ref="gemma-4-e4b-qat",
            source_lang="de",
            target_lang="en",
        )

    assert "Refinement metrics update failed" in caplog.text


def test_a_shadow_candidate_that_never_ran_is_still_counted(monkeypatch):
    """SKIPPED_OVERLOAD and SUBMISSION_FAILED bypass `_emit_outcome` entirely.

    `_emit_candidate_not_run` calls `_emit_attempt` directly, so this is the
    regression check for the gap the review found: those two outcome codes
    reached telemetry but never reached the counter while the recording lived
    in `_emit_outcome` instead of `_emit_attempt`.
    """
    from prometheus_client import CollectorRegistry

    from services.api_gateway.refinement_metrics import RefinementMetrics

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
    registry = CollectorRegistry()
    refiner.refinement_metrics = RefinementMetrics(registry)
    refiner.pending = refiner.queue_limit  # force the overload path

    monkeypatch.setattr(
        mod.OllamaTranslationRefiner,
        "refine",
        Mock(return_value=mod.RefinementOutcome(text="refined", changed=True)),
    )

    outcome = refiner.refine("Hallo", "de", "en")

    assert outcome.candidate_status == "skipped_overload"
    value = registry.get_sample_value(
        "refinement_attempts_total",
        {"outcome": "skipped_overload", "model_ref": "candidate"},
    )
    assert value == 1.0


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
    monkeypatch.setattr(refiner.executor, "submit", submit)

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
        refiner.executor,
        "submit",
        Mock(side_effect=RuntimeError("executor shut down")),
    )

    outcome = refiner.refine("Hallo", "de", "en")

    assert outcome.candidate_status == "submission_failed"
    assert refiner.pending == 0


def test_each_shadow_refiner_owns_its_candidate_worker_until_shutdown(monkeypatch):
    """Two apps' refiners never share a worker, and the lifespan's shutdown stops one."""
    mod = importlib.import_module(MODULE_PATH)
    first, second = (
        mod.ShadowComparisonRefiner(
            endpoint="http://ollama:11434",
            model="primary",
            candidate_model="candidate",
            queue_limit=1,
            timeout_seconds=1.0,
            temperature=0.2,
            max_retries=1,
        )
        for _ in range(2)
    )
    monkeypatch.setattr(
        mod.OllamaTranslationRefiner,
        "refine",
        Mock(return_value=mod.RefinementOutcome(text="refined", changed=True)),
    )
    assert first.executor is not second.executor

    first.shutdown()

    assert first.refine("Hallo", "de", "en").candidate_status == "submission_failed"
    assert first.pending == 0
    second.shutdown()


def test_vllm_refiner_posts_a_chat_completion_with_thinking_off(monkeypatch):
    """Thinking inside a 4 s budget is what made gpt-oss:20b unusable."""
    mod = reload_module({"LLM_REFINEMENT_ENABLED": "0"})
    response = Mock()
    response.json.return_value = {"choices": [{"message": {"content": "Guten Tag."}}]}
    monkeypatch.setattr(mod.requests, "post", Mock(return_value=response))

    refiner = mod.VllmTranslationRefiner(
        endpoint="http://vllm:8000",
        model="gemma-4-e4b-qat",
        timeout_seconds=4.0,
        temperature=0.7,
        max_retries=1,
    )

    outcome = refiner._perform_refinement("Guten tag", "ar", "de")

    assert outcome.text == "Guten Tag."
    mod.requests.post.assert_called_once_with(
        "http://vllm:8000/v1/chat/completions",
        json={
            "model": "gemma-4-e4b-qat",
            "messages": [{"role": "user", "content": ANY}],
            "stream": False,
            "temperature": 0.7,
            "max_tokens": 256,
            "chat_template_kwargs": {"enable_thinking": False},
        },
        timeout=4.0,
    )
    sent_messages = mod.requests.post.call_args.kwargs["json"]["messages"]
    assert sent_messages[0]["role"] == "user"


def test_vllm_refiner_reads_an_empty_choice_list_as_an_empty_response():
    mod = reload_module({"LLM_REFINEMENT_ENABLED": "0"})
    refiner = mod.VllmTranslationRefiner(
        endpoint="http://vllm:8000",
        model="m",
        timeout_seconds=4.0,
        temperature=0.7,
        max_retries=1,
    )

    assert refiner._extract_text({"choices": []}) == ""
    assert refiner._extract_text({"choices": [{"message": {"content": " x "}}]}) == "x"


def test_vllm_refiner_discards_a_truncated_response(monkeypatch, caplog):
    """A response cut off at the token cap must never replace the original
    translation: it comes back mid-sentence and is then spoken aloud by TTS,
    which is worse than leaving the unrefined translation in place."""
    import logging

    mod = reload_module({"LLM_REFINEMENT_ENABLED": "0"})
    response = Mock()
    response.json.return_value = {
        "choices": [
            {
                "message": {"content": "This is a long sentence that got cut off mid"},
                "finish_reason": "length",
            }
        ]
    }
    monkeypatch.setattr(mod.requests, "post", Mock(return_value=response))

    refiner = mod.VllmTranslationRefiner(
        endpoint="http://vllm:8000",
        model="m",
        timeout_seconds=4.0,
        temperature=0.7,
        max_retries=1,
        max_tokens=256,
    )

    with caplog.at_level(logging.WARNING):
        outcome = refiner._perform_refinement("Guten tag", "de", "en")

    assert outcome.text == "Guten tag"
    assert outcome.changed is False
    assert outcome.error == "empty_response"
    assert outcome.error_code == mod.QualityErrorCode.UPSTREAM_MALFORMED_RESPONSE
    assert any("truncated" in r.getMessage() for r in caplog.records)


def test_vllm_refiner_accepts_a_normal_stop_response():
    mod = reload_module({"LLM_REFINEMENT_ENABLED": "0"})
    refiner = mod.VllmTranslationRefiner(
        endpoint="http://vllm:8000",
        model="m",
        timeout_seconds=4.0,
        temperature=0.7,
        max_retries=1,
    )

    text = refiner._extract_text(
        {"choices": [{"message": {"content": "Guten Tag."}, "finish_reason": "stop"}]}
    )

    assert text == "Guten Tag."


def test_extract_text_reads_the_ollama_response_field():
    mod = reload_module({"LLM_REFINEMENT_ENABLED": "0"})
    refiner = mod.OllamaTranslationRefiner(
        "http://ollama:11434", "phi4-mini", 4.0, 0.7, 1, False
    )

    assert refiner._extract_text({"response": "  Guten Tag.  "}) == "Guten Tag."
    assert refiner._extract_text({}) == ""
