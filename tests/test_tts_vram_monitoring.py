"""The TTS cache and VRAM monitoring queries only series TTS exports (#224).

A renamed metric leaves an alert that can never fire and a panel that stays
empty without anything failing, as the audio-storage alerts did (#426).
"""

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TTS_METRIC = re.compile(r"\btts_[a-z_]+\b")


def _exported_tts_metrics():
    source = (ROOT / "services/tts/app.py").read_text()
    names = set(re.findall(r'(?:Gauge|Counter)\(\s*"(tts_[a-z_]+)"', source, re.MULTILINE))
    assert names, "no TTS metric definitions found"
    return names


def _alert_rules():
    groups = yaml.safe_load((ROOT / "monitoring/alert_rules.yml").read_text())["groups"]
    return {rule["alert"]: rule for group in groups for rule in group["rules"] if "alert" in rule}


def _overview_exprs():
    dashboard = json.loads((ROOT / "monitoring/grafana-dashboards/ssf-overview.json").read_text())
    return {
        panel["title"]: [target["expr"] for target in panel.get("targets", [])]
        for panel in dashboard["panels"]
    }


def test_vram_budget_alert_compares_the_process_with_its_budget():
    rule = _alert_rules()["TTSVRAMOverBudget"]
    assert rule["expr"] == "tts_process_vram_bytes > tts_vram_budget_bytes"
    assert rule["labels"]["severity"] == "warning"


def test_overview_shows_voice_occupancy_and_vram_against_budget():
    exprs = _overview_exprs()
    assert any("tts_voice_loaded" in expr for expr in exprs["TTS Voices Loaded"])
    vram = " ".join(exprs["TTS VRAM"])
    assert "tts_process_vram_bytes" in vram
    assert "tts_vram_budget_bytes" in vram
    assert any("DCGM_FI_DEV_FB_FREE" in expr for expr in exprs["GPU Memory Headroom"])


def test_every_tts_series_queried_is_exported():
    queried = {
        name for rule in _alert_rules().values() for name in TTS_METRIC.findall(rule["expr"])
    }
    queried |= {
        name
        for panel_exprs in _overview_exprs().values()
        for expr in panel_exprs
        for name in TTS_METRIC.findall(expr)
    }
    exported = _exported_tts_metrics()
    # prometheus_client appends _total to counters.
    exported |= {f"{name}_total" for name in exported if not name.endswith("_total")}
    assert queried - exported == set()
