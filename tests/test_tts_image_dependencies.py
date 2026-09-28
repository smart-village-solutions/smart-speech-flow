"""piper-tts is installed without its dependencies.

piper-tts 1.8.0 declares onnxruntime and pathvalidate. onnxruntime is the CPU
build and installs into the same module directory as onnxruntime-gpu, so the
service lock carries onnxruntime-gpu instead, piper-tts is pinned on its own
and installed with --no-deps, and every other declared dependency has to be in
the lock by hand.
"""

from __future__ import annotations

import re
from pathlib import Path

TTS = Path(__file__).resolve().parents[1] / "services" / "tts"
PIPER_DEPENDENCIES_BESIDES_ONNXRUNTIME = {"pathvalidate", "numpy"}


def _pins(path: Path) -> dict[str, str]:
    return dict(re.findall(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", path.read_text(), re.MULTILINE))


def test_the_lock_has_the_gpu_onnxruntime_and_not_the_cpu_one():
    pins = _pins(TTS / "requirements.txt")
    assert "onnxruntime-gpu" in pins
    assert "onnxruntime" not in pins
    assert "piper-tts" not in pins


def test_every_other_piper_dependency_is_locked():
    pins = _pins(TTS / "requirements.txt")
    assert PIPER_DEPENDENCIES_BESIDES_ONNXRUNTIME <= set(pins)
    assert pins["pathvalidate"].startswith("3.")


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
    assert "RUN python3 -m services.tts.fetch_voices" in dockerfile
    assert "TTS_VOICE_DIR=/opt/tts-voices" in dockerfile
    assert '"services.tts.app:app"' in dockerfile
    for module in _modules_the_app_imports():
        assert f"services/tts/{module}" in dockerfile


def _modules_the_app_imports() -> set[str]:
    """app.py and every services.tts module it reaches, as file names.

    The Dockerfile copies modules by name, so one missing from the list only
    fails when the container starts.
    """
    found: set[str] = set()
    pending = ["app"]
    while pending:
        module = pending.pop()
        if f"{module}.py" in found:
            continue
        found.add(f"{module}.py")
        pending += _tts_imports((TTS / f"{module}.py").read_text())
    return found


# [ \t]*, not \s*: with MULTILINE, \s* also spans newlines and is super-linear.
_MODULE_IMPORT = re.compile(
    r"^[ \t]*(?:from (?:services\.tts\.|\.)(\w+) import|import services\.tts\.(\w+))",
    re.MULTILINE,
)
_PACKAGE_IMPORT = re.compile(r"^[ \t]*from (?:services\.tts|\.) import ([\w ,]+)", re.MULTILINE)


def _tts_imports(source: str) -> set[str]:
    """Names of the services.tts modules a source file imports, in any form."""
    modules = {first or second for first, second in _MODULE_IMPORT.findall(source)}
    for names in _PACKAGE_IMPORT.findall(source):
        modules |= {name.split()[0] for name in names.split(",") if name.strip()}
    return modules


def test_the_import_walk_reaches_every_engine():
    assert {"vram.py", "piper_engine.py", "mms_engine.py", "speech_text.py"} <= (
        _modules_the_app_imports()
    )


def test_the_voices_stage_does_not_depend_on_the_python_requirements():
    """A requirements change must not re-download the voices."""
    dockerfile = (TTS / "Dockerfile").read_text()
    stage = re.search(r"^FROM (\S+) AS voices$", dockerfile, re.MULTILINE)
    assert stage, "no voices stage"
    assert stage.group(1) == "ubuntu:24.04"


def test_the_import_walk_recognises_every_import_form():
    source = (
        "from services.tts.vram import ProcessVram\n"
        "    from services.tts import voices, speech_text as text\n"
        "import services.tts.piper_engine\n"
        "from .mms_engine import MmsSpeaker\n"
        "from . import fetch_voices\n"
        "from services.gpu_metrics import collect_gpu_metrics\n"
    )
    assert _tts_imports(source) == {
        "vram",
        "voices",
        "speech_text",
        "piper_engine",
        "mms_engine",
        "fetch_voices",
    }
