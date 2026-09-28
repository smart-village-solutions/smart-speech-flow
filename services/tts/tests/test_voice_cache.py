"""The voice set is loaded once and never grows, evicts or reloads (#224)."""

import math
import os
import random
import re

import pytest

from services.tts.tests.conftest import FakeNvml

LANGS = ["de", "en", "ar", "tr", "ru", "uk", "am", "ti", "ku", "fa"]
MIB = 1024 * 1024


def _metric(text, name, **labels):
    selector = ",".join(f'{key}="{value}"' for key, value in sorted(labels.items()))
    pattern = rf"^{name}{{{selector}}} (\S+)$" if labels else rf"^{name} (\S+)$"
    match = re.search(pattern, text, re.MULTILINE)
    return None if match is None else float(match[1])


@pytest.fixture
def nvml():
    return FakeNvml(os.getpid())


@pytest.fixture
def voice_costs_mib():
    return {"de": 300, "en": 60, "am": 140}


def test_requests_in_every_language_load_nothing_more(client, load_counts, nvml):
    held_after_startup = nvml.held
    order = LANGS * 5
    random.Random(224).shuffle(order)

    for lang in order:
        assert client.post("/synthesize", json={"text": "Hallo", "lang": lang}).status_code == 200

    assert load_counts == {lang: 1 for lang in LANGS}
    assert client.get("/health").json()["vram"]["process_bytes"] == held_after_startup


@pytest.mark.parametrize("failing_langs", [{"fa"}])
def test_a_voice_that_failed_to_load_is_never_retried(client, load_counts, failing_langs):
    statuses = [
        client.post("/synthesize", json={"text": "Salam", "lang": "fa"}).status_code
        for _ in range(3)
    ]
    assert statuses == [503, 503, 503]
    assert load_counts["fa"] == 1


def test_health_reports_what_each_voice_cost_to_load(client):
    vram = client.get("/health").json()["vram"]
    assert vram["voice_load_bytes"] == {
        lang: {"de": 300, "en": 60, "am": 140}.get(lang, 0) * MIB for lang in LANGS
    }
    assert vram["process_bytes"] == 500 * MIB
    assert vram["budget_bytes"] == 2048 * MIB
    assert vram["within_budget"] is True


def test_over_budget_is_reported_without_failing_health(monkeypatch, request):
    monkeypatch.setenv("TTS_VRAM_BUDGET_MIB", "400")
    data = request.getfixturevalue("client").get("/health").json()
    assert data["vram"]["within_budget"] is False
    assert data["status"] == "ok"


def test_growth_after_startup_is_seen_live(client, nvml):
    nvml.held += 2000 * MIB
    vram = client.get("/health").json()["vram"]
    assert vram["process_bytes"] == 2500 * MIB
    assert vram["within_budget"] is False


@pytest.mark.parametrize("nvml", [None])
def test_without_nvml_the_footprint_is_unknown(client, nvml):
    vram = client.get("/health").json()["vram"]
    assert vram["process_bytes"] is None
    assert vram["within_budget"] is None
    assert vram["voice_load_bytes"] == {}
    assert math.isnan(_metric(client.get("/metrics").text, "tts_process_vram_bytes"))


@pytest.mark.parametrize("failing_langs", [{"fa"}])
def test_metrics_expose_occupancy_footprint_and_budget(client, failing_langs):
    text = client.get("/metrics").text
    assert _metric(text, "tts_voice_loaded", lang="de", engine="piper") == 1
    assert _metric(text, "tts_voice_loaded", lang="am", engine="mms") == 1
    assert _metric(text, "tts_voice_loaded", lang="fa", engine="piper") == 0
    assert _metric(text, "tts_voice_vram_bytes", lang="de") == 300 * MIB
    assert _metric(text, "tts_voice_vram_bytes", lang="fa") is None
    assert _metric(text, "tts_process_vram_bytes") == 500 * MIB
    assert _metric(text, "tts_vram_budget_bytes") == 2048 * MIB
