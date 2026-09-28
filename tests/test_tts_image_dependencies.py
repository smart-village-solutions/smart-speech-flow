"""piper-tts is installed without its dependencies.

piper-tts 1.8.0 declares onnxruntime and pathvalidate. onnxruntime is the CPU
build and installs into the same module directory as onnxruntime-gpu, so the
service lock carries onnxruntime-gpu instead, piper-tts is pinned on its own
and installed with --no-deps, and every other declared dependency has to be in
the lock by hand.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TTS = ROOT / "services" / "tts"
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


def _runtime_stage() -> str:
    dockerfile = (TTS / "Dockerfile").read_text()
    return dockerfile[dockerfile.rindex("\nFROM ") :]


def test_the_image_copies_every_service_module_by_glob():
    """Copying the modules by name let a new one build fine and crash at import."""
    assert "COPY services/tts/*.py ./services/tts/" in _runtime_stage()


def _services_imports(path: Path) -> set[Path]:
    """Files of the services.* modules a file imports, in any syntactic form."""
    package = path.relative_to(ROOT).parent.parts
    dotted: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            dotted |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = ".".join(package[: len(package) - node.level + 1]) if node.level else ""
            module = ".".join(part for part in (base, node.module or "") if part)
            dotted |= {module} | {f"{module}.{alias.name}" for alias in node.names}
    files = {
        ROOT / f"{name.replace('.', '/')}.py" for name in dotted if name.startswith("services")
    }
    return {file for file in files if file.is_file()}


def _modules_outside_the_glob() -> set[str]:
    """services.* files the TTS modules reach that services/tts/*.py does not cover."""
    seen: set[Path] = set()
    pending = [path for path in TTS.glob("*.py")]
    while pending:
        path = pending.pop()
        if path not in seen:
            seen.add(path)
            pending += _services_imports(path)
    return {path.relative_to(ROOT).as_posix() for path in seen if path.parent != TTS}


def test_the_image_copies_the_shared_modules_the_service_imports():
    runtime = _runtime_stage()
    assert _modules_outside_the_glob() == {
        "services/gpu_metrics.py",
        "services/resource_metrics.py",
    }
    for module in _modules_outside_the_glob():
        assert module in runtime


def test_the_import_reader_understands_every_import_form(tmp_path, monkeypatch):
    package = tmp_path / "services" / "tts"
    package.mkdir(parents=True)
    for name in ("vram", "voices", "speech_text", "piper_engine", "mms_engine"):
        (package / f"{name}.py").write_text("")
    (tmp_path / "services" / "gpu_metrics.py").write_text("")
    probe = package / "probe.py"
    probe.write_text(
        "from services.tts.vram import ProcessVram\n"
        "from services.tts import (\n    voices,\n    speech_text as text,\n)\n"
        "import services.tts.piper_engine\n"
        "from .mms_engine import MmsSpeaker\n"
        "from ..gpu_metrics import collect_gpu_metrics\n"
        "import numpy\n"
    )
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    assert {p.relative_to(tmp_path).as_posix() for p in _services_imports(probe)} == {
        "services/tts/vram.py",
        "services/tts/voices.py",
        "services/tts/speech_text.py",
        "services/tts/piper_engine.py",
        "services/tts/mms_engine.py",
        "services/gpu_metrics.py",
    }


def test_the_voices_stage_does_not_depend_on_the_python_requirements():
    """A requirements change must not re-download the voices."""
    dockerfile = (TTS / "Dockerfile").read_text()
    stage = re.search(r"^FROM (\S+) AS voices$", dockerfile, re.MULTILINE)
    assert stage, "no voices stage"
    assert stage.group(1) == "ubuntu:24.04"
