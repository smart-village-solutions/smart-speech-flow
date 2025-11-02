import importlib
import os

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