"""Refinement configuration precedence and startup validation (issue #222, ADR-002).

Precedence: LLM_REFINEMENT_ENABLED=false is a kill switch that wins over any
mode. Otherwise an explicit LLM_REFINEMENT_MODE wins; ENABLED=true without a
mode means primary_only; nothing set means disabled.
"""

import logging

import pytest

from services.api_gateway import translation_refiner as refiner_module

REFINEMENT_VARS = (
    "LLM_REFINEMENT_ENABLED",
    "LLM_REFINEMENT_MODE",
    "LLM_REFINEMENT_MODEL",
    "LLM_REFINEMENT_PRIMARY_MODEL",
    "LLM_REFINEMENT_CANDIDATE_MODEL",
    "LLM_REFINEMENT_SHADOW_QUEUE_LIMIT",
    "LLM_REFINEMENT_ENDPOINT",
    "LLM_REFINEMENT_TIMEOUT",
    "LLM_REFINEMENT_TEMPERATURE",
    "LLM_REFINEMENT_THINK",
    "LLM_REFINEMENT_MAX_RETRIES",
    "LLM_REFINEMENT_SKIP_TARGET_LANGUAGES",
    "LLM_REFINEMENT_BACKEND",
    "LLM_REFINEMENT_MAX_TOKENS",
)


@pytest.fixture
def env(monkeypatch):
    for name in REFINEMENT_VARS:
        monkeypatch.delenv(name, raising=False)

    def apply(**values: str) -> None:
        for name, value in values.items():
            monkeypatch.setenv(f"LLM_REFINEMENT_{name}", value)

    return apply


@pytest.mark.parametrize("mode", ["primary_only", "candidate_only", "shadow_compare", "disabled"])
@pytest.mark.parametrize("enabled", ["false", "0", "no", "off", "FALSE", " false "])
def test_enabled_false_disables_refinement_whatever_the_mode(env, mode, enabled):
    env(ENABLED=enabled, MODE=mode)

    assert isinstance(
        refiner_module.get_translation_refiner(), refiner_module.NoOpTranslationRefiner
    )


@pytest.mark.parametrize(
    ("values", "expected_type_name", "expected_model"),
    [
        ({}, "NoOpTranslationRefiner", None),
        ({"ENABLED": ""}, "NoOpTranslationRefiner", None),
        ({"ENABLED": "true"}, "OllamaTranslationRefiner", "gpt-oss:20b"),
        ({"MODE": "primary_only"}, "OllamaTranslationRefiner", "gpt-oss:20b"),
        ({"ENABLED": "true", "MODE": "disabled"}, "NoOpTranslationRefiner", None),
        (
            {"ENABLED": "true", "MODE": "candidate_only"},
            "OllamaTranslationRefiner",
            "phi4-mini",
        ),
        (
            {"ENABLED": "yes", "MODE": " Shadow_Compare "},
            "ShadowComparisonRefiner",
            "gpt-oss:20b",
        ),
    ],
)
def test_precedence_between_enabled_and_mode(env, values, expected_type_name, expected_model):
    env(**values)

    refiner = refiner_module.get_translation_refiner()

    assert type(refiner) is getattr(refiner_module, expected_type_name)
    if expected_model is not None:
        assert refiner.model == expected_model


def test_kill_switch_overriding_an_active_mode_is_logged(env, caplog):
    env(ENABLED="false", MODE="primary_only")

    with caplog.at_level(logging.WARNING, logger=refiner_module.logger.name):
        refiner_module.get_translation_refiner()

    warning = " ".join(r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)
    assert "LLM_REFINEMENT_ENABLED" in warning
    assert "primary_only" in warning


def test_kill_switch_works_even_when_other_values_are_invalid(env):
    env(ENABLED="false", MODE="primary_only", TIMEOUT="abc", MAX_RETRIES="-3")

    assert isinstance(
        refiner_module.get_translation_refiner(), refiner_module.NoOpTranslationRefiner
    )


@pytest.mark.parametrize(
    ("values", "variable", "offending"),
    [
        ({"ENABLED": "flase"}, "LLM_REFINEMENT_ENABLED", "flase"),
        ({"MODE": "primary"}, "LLM_REFINEMENT_MODE", "primary"),
        ({"MODE": "primary_only", "TIMEOUT": "abc"}, "LLM_REFINEMENT_TIMEOUT", "abc"),
        ({"MODE": "primary_only", "TIMEOUT": "2.9"}, "LLM_REFINEMENT_TIMEOUT", "2.9"),
        ({"MODE": "primary_only", "TIMEOUT": "5.1"}, "LLM_REFINEMENT_TIMEOUT", "5.1"),
        ({"MODE": "primary_only", "TIMEOUT": "nan"}, "LLM_REFINEMENT_TIMEOUT", "nan"),
        (
            {"MODE": "primary_only", "TEMPERATURE": "hot"},
            "LLM_REFINEMENT_TEMPERATURE",
            "hot",
        ),
        (
            {"MODE": "primary_only", "TEMPERATURE": "-0.1"},
            "LLM_REFINEMENT_TEMPERATURE",
            "-0.1",
        ),
        (
            {"MODE": "primary_only", "MAX_RETRIES": "x"},
            "LLM_REFINEMENT_MAX_RETRIES",
            "x",
        ),
        (
            {"MODE": "primary_only", "MAX_RETRIES": "0"},
            "LLM_REFINEMENT_MAX_RETRIES",
            "0",
        ),
        (
            {"MODE": "primary_only", "MAX_RETRIES": "1.5"},
            "LLM_REFINEMENT_MAX_RETRIES",
            "1.5",
        ),
        ({"MODE": "primary_only", "THINK": "maybe"}, "LLM_REFINEMENT_THINK", "maybe"),
        (
            {"MODE": "shadow_compare", "SHADOW_QUEUE_LIMIT": "0"},
            "LLM_REFINEMENT_SHADOW_QUEUE_LIMIT",
            "0",
        ),
    ],
)
def test_invalid_values_fail_startup_naming_the_variable(env, values, variable, offending):
    env(**values)

    with pytest.raises(ValueError) as excinfo:
        refiner_module.get_translation_refiner()

    message = str(excinfo.value)
    assert variable in message
    assert repr(offending) in message


def test_invalid_mode_error_lists_the_accepted_modes(env):
    env(MODE="primary")

    with pytest.raises(ValueError) as excinfo:
        refiner_module.get_translation_refiner()

    for accepted in ("disabled", "primary_only", "candidate_only", "shadow_compare"):
        assert accepted in str(excinfo.value)


@pytest.mark.parametrize(("timeout", "expected"), [("3.0", 3.0), ("5.0", 5.0), ("4", 4.0)])
def test_timeout_bounds_are_inclusive(env, timeout, expected):
    env(MODE="primary_only", TIMEOUT=timeout)

    assert refiner_module.get_translation_refiner().timeout_seconds == pytest.approx(expected)


def test_valid_tuning_values_reach_the_refiner(env):
    env(
        MODE="shadow_compare",
        TIMEOUT="3.5",
        TEMPERATURE="0",
        MAX_RETRIES="3",
        THINK="on",
        SHADOW_QUEUE_LIMIT="2",
    )

    refiner = refiner_module.get_translation_refiner()

    assert refiner.timeout_seconds == pytest.approx(3.5)
    assert refiner.temperature == pytest.approx(0.0)
    assert refiner.max_retries == 3
    assert refiner.think is True
    assert refiner.queue_limit == 2


def test_skip_list_defaults_to_the_four_unsupported_languages(env):
    env(ENABLED="true")

    refiner = refiner_module.get_translation_refiner()

    assert refiner.skip_target_languages == frozenset({"am", "ti", "ku", "fa"})


def test_skip_list_can_be_emptied(env):
    env(ENABLED="true", SKIP_TARGET_LANGUAGES="")

    refiner = refiner_module.get_translation_refiner()

    assert refiner.skip_target_languages == frozenset()


def test_backend_selects_the_vllm_refiner(env):
    env(ENABLED="true", BACKEND="vllm")

    refiner = refiner_module.get_translation_refiner()

    assert type(refiner).__name__ == "VllmTranslationRefiner"
    assert refiner.endpoint == "http://vllm:8000"


def test_blank_endpoint_falls_through_to_the_backend_default(env):
    """Compose always sets LLM_REFINEMENT_ENDPOINT, even to an empty string,
    so the variable is present but blank rather than absent. That must still
    reach the backend-aware default -- otherwise the one-variable switch to
    vllm silently keeps talking to Ollama."""
    env(ENABLED="true", BACKEND="vllm", ENDPOINT="")

    refiner = refiner_module.get_translation_refiner()

    assert refiner.endpoint == "http://vllm:8000"


def test_non_blank_endpoint_still_overrides_the_backend_default(env):
    env(ENABLED="true", BACKEND="vllm", ENDPOINT="http://vllm.internal:9000")

    refiner = refiner_module.get_translation_refiner()

    assert refiner.endpoint == "http://vllm.internal:9000"


def test_backend_defaults_to_ollama(env):
    env(ENABLED="true")

    refiner = refiner_module.get_translation_refiner()

    assert type(refiner).__name__ == "OllamaTranslationRefiner"
    assert refiner.endpoint == "http://ollama:11434"


def test_an_unknown_backend_stops_startup(env):
    env(ENABLED="true", BACKEND="vlm")

    with pytest.raises(ValueError, match="LLM_REFINEMENT_BACKEND"):
        refiner_module.get_translation_refiner()


def test_shadow_compare_is_rejected_on_vllm(env):
    """The shadow refiner speaks Ollama's API; failing loudly beats a silent
    fallback to the wrong backend."""
    env(MODE="shadow_compare", BACKEND="vllm")

    with pytest.raises(ValueError, match="shadow_compare"):
        refiner_module.get_translation_refiner()


def test_max_tokens_reaches_the_vllm_refiner(env):
    env(ENABLED="true", BACKEND="vllm", MAX_TOKENS="128")

    refiner = refiner_module.get_translation_refiner()

    assert refiner.max_tokens == 128


def test_max_tokens_below_the_minimum_fails_startup(env):
    env(ENABLED="true", BACKEND="vllm", MAX_TOKENS="8")

    with pytest.raises(ValueError, match="LLM_REFINEMENT_MAX_TOKENS"):
        refiner_module.get_translation_refiner()
