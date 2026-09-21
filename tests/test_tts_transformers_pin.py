"""The TTS image must not ship transformers 5.17.0.

5.17.0 added an unconditional ``output.to(dtype=self.model.dtype)`` to the
text-to-audio pipeline (``transformers/pipelines/text_to_audio.py:197``). For a
tokenizer-backed model such as VITS that ``output`` is a ``BatchEncoding``,
whose ``.to()`` accepts no ``dtype``, so every synthesis raises ``TypeError``
and the service answers 500. A Dependabot bump (``fc25372``) took the floor to
5.17.0 and the next production deploy lost TTS entirely.

This guard reads the lock rather than the source pin: the lock is what the
Dockerfile installs, and a bump that edits only ``requirements.in`` would
otherwise pass while the image still carried the broken release.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TTS_LOCK = REPO_ROOT / "services" / "tts" / "requirements.txt"
TTS_SOURCE_PIN = REPO_ROOT / "services" / "tts" / "requirements.in"

BROKEN_VERSION = (5, 17, 0)


def _version_tuple(raw: str) -> tuple[int, ...]:
    return tuple(int(part) for part in raw.split(".") if part.isdigit())


def _locked_transformers_version() -> str:
    match = re.search(r"^transformers==([0-9][^\s\\]*)", TTS_LOCK.read_text(), re.MULTILINE)
    assert match, f"transformers is not pinned in {TTS_LOCK}"
    return match.group(1)


def test_locked_transformers_predates_the_text_to_audio_regression():
    locked = _locked_transformers_version()

    assert _version_tuple(locked) < BROKEN_VERSION, (
        f"services/tts pins transformers {locked}, which is 5.17.0 or newer. "
        "That release breaks every VITS synthesis with "
        "\"BatchEncoding.to() got an unexpected keyword argument 'dtype'\". "
        "Raise the ceiling in requirements.in only once a release fixes it."
    )


def test_the_source_pin_carries_the_ceiling():
    """A lock is regenerated from the .in file, so the ceiling has to live there too."""
    assert "transformers>=" in TTS_SOURCE_PIN.read_text()
    assert "<5.17.0" in TTS_SOURCE_PIN.read_text(), (
        "requirements.in must cap transformers below 5.17.0, or the next "
        "pip-compile silently restores the broken release."
    )
