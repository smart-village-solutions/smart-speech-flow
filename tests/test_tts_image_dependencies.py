"""piper-tts is installed without its dependencies.

Its one runtime dependency besides numpy, onnxruntime, is the CPU build and
installs into the same module directory as onnxruntime-gpu. The service lock
carries onnxruntime-gpu instead, and piper-tts is pinned on its own and
installed with --no-deps.
"""

from __future__ import annotations

import re
from pathlib import Path

TTS = Path(__file__).resolve().parents[1] / "services" / "tts"


def _pins(path: Path) -> dict[str, str]:
    return dict(re.findall(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", path.read_text(), re.MULTILINE))


def test_the_lock_has_the_gpu_onnxruntime_and_not_the_cpu_one():
    pins = _pins(TTS / "requirements.txt")
    assert "onnxruntime-gpu" in pins
    assert "onnxruntime" not in pins
    assert "piper-tts" not in pins
    assert "numpy" in pins


def test_piper_is_pinned_alone_with_a_hash():
    text = (TTS / "requirements-piper.txt").read_text()
    assert _pins(TTS / "requirements-piper.txt") == {"piper-tts": "1.8.0"}
    assert "--hash=sha256:25b4d3f31ff70c8fa7151908e00aaa5650cbdf16bca8fcf21299f3941b89a7d3" in text


def test_the_dockerfile_downloads_piper_without_dependencies():
    dockerfile = (TTS / "Dockerfile").read_text()
    step = re.search(r"pip download(?:[^\n]*\\\n)*[^\n]*requirements-piper\.txt", dockerfile)
    assert step, "no pip download step for requirements-piper.txt"
    assert "--no-deps" in step.group()
    assert "--require-hashes" in step.group()


def test_the_image_bakes_the_voices_in_and_runs_the_package():
    dockerfile = (TTS / "Dockerfile").read_text()
    assert "python3 -m services.tts.fetch_voices /opt/tts-voices" in dockerfile
    assert "TTS_VOICE_DIR=/opt/tts-voices" in dockerfile
    assert '"services.tts.app:app"' in dockerfile
    for module in ("speech_text.py", "voices.py", "piper_engine.py", "mms_engine.py", "app.py"):
        assert f"services/tts/{module}" in dockerfile
