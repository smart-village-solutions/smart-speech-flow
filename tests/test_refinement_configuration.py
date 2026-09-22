"""Refinement configuration precedence and startup validation (issue #222, ADR-002).

Precedence: LLM_REFINEMENT_ENABLED=false is a kill switch that wins over any
mode. Otherwise an explicit LLM_REFINEMENT_MODE wins; ENABLED=true without a
mode means primary_only; nothing set means disabled.
"""

import logging

import pytest

from services.api_gateway import translation_refiner as refiner_module
from services.api_gateway.translation_refiner import (
    NoOpTranslationRefiner,
    OllamaTranslationRefiner,
    ShadowComparisonRefiner,
    get_translation_refiner,
)

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

    assert isinstance(get_translation_refiner(), NoOpTranslationRefiner)


@pytest.mark.parametrize(
    ("values", "expected_type", "expected_model"),
    [
        ({}, NoOpTranslationRefiner, None),
        ({"ENABLED": ""}, NoOpTranslationRefiner, None),
        ({"ENABLED": "true"}, OllamaTranslationRefiner, "gpt-oss:20b"),
        ({"MODE": "primary_only"}, OllamaTranslationRefiner, "gpt-oss:20b"),
        ({"ENABLED": "true", "MODE": "disabled"}, NoOpTranslationRefiner, None),
        (
            {"ENABLED": "true", "MODE": "candidate_only"},
            OllamaTranslationRefiner,
            "phi4-mini",
        ),
        (
            {"ENABLED": "yes", "MODE": " Shadow_Compare "},
            ShadowComparisonRefiner,
            "gpt-oss:20b",
        ),
    ],
)
def test_precedence_between_enabled_and_mode(env, values, expected_type, expected_model):
    env(**values)

    refiner = get_translation_refiner()

    assert type(refiner) is expected_type
    if expected_model is not None:
        assert refiner.model == expected_model


def test_kill_switch_overriding_an_active_mode_is_logged(env, caplog):
    env(ENABLED="false", MODE="primary_only")

    with caplog.at_level(logging.WARNING, logger=refiner_module.logger.name):
        get_translation_refiner()

    warning = " ".join(r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)
    assert "LLM_REFINEMENT_ENABLED" in warning
    assert "primary_only" in warning


def test_kill_switch_works_even_when_other_values_are_invalid(env):
    env(ENABLED="false", MODE="primary_only", TIMEOUT="abc", MAX_RETRIES="-3")

    assert isinstance(get_translation_refiner(), NoOpTranslationRefiner)


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
        get_translation_refiner()

    message = str(excinfo.value)
    assert variable in message
    assert repr(offending) in message


def test_invalid_mode_error_lists_the_accepted_modes(env):
    env(MODE="primary")

    with pytest.raises(ValueError) as excinfo:
        get_translation_refiner()

    for accepted in ("disabled", "primary_only", "candidate_only", "shadow_compare"):
        assert accepted in str(excinfo.value)


@pytest.mark.parametrize("timeout", ["3.0", "5.0", "4"])
def test_timeout_bounds_are_inclusive(env, timeout):
    env(MODE="primary_only", TIMEOUT=timeout)

    assert get_translation_refiner().timeout_seconds == float(timeout)


def test_valid_tuning_values_reach_the_refiner(env):
    env(
        MODE="shadow_compare",
        TIMEOUT="3.5",
        TEMPERATURE="0",
        MAX_RETRIES="3",
        THINK="on",
        SHADOW_QUEUE_LIMIT="2",
    )

    refiner = get_translation_refiner()

    assert refiner.timeout_seconds == 3.5
    assert refiner.temperature == 0.0
    assert refiner.max_retries == 3
    assert refiner.think is True
    assert refiner.queue_limit == 2
