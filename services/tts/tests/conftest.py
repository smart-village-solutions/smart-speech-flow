import sys
import types

import numpy as np
import pytest
from fastapi.testclient import TestClient


def _install_fake_torch() -> None:
    fake_torch = sys.modules.get("torch")
    if fake_torch is None:
        fake_torch = types.ModuleType("torch")
        sys.modules["torch"] = fake_torch

    class _FakeCuda:
        @staticmethod
        def is_available():
            return False

        @staticmethod
        def device_count():
            return 0

        @staticmethod
        def memory_allocated(_device_idx=0):
            return 0

        @staticmethod
        def memory_reserved(_device_idx=0):
            return 0

        @staticmethod
        def manual_seed(_seed):
            return None

    fake_torch.cuda = _FakeCuda()
    fake_torch.manual_seed = lambda _seed: None
    fake_torch.device = getattr(fake_torch, "device", lambda name: name)
    fake_torch.float16 = getattr(fake_torch, "float16", "float16")
    fake_torch.float32 = getattr(fake_torch, "float32", "float32")


def _install_fake_soundfile() -> None:
    if "soundfile" in sys.modules:
        return

    def _write(target, audio, sampling_rate, format="WAV"):
        target.write(b"RIFFfakeWAVEfmt " + bytes(str(sampling_rate), "ascii"))

    fake_soundfile = types.ModuleType("soundfile")
    fake_soundfile.write = _write
    sys.modules["soundfile"] = fake_soundfile


_install_fake_torch()
_install_fake_soundfile()


class FakeSpeaker:
    def __init__(self, device="cuda"):
        self.device = device
        self.calls = []

    def synthesize(self, text, seed):
        self.calls.append((text, seed))
        return np.array([0.1, -0.1, 0.0, 0.2], dtype=np.float32), 22050


@pytest.fixture
def failing_langs():
    return set()


@pytest.fixture
def speakers():
    return {}


@pytest.fixture
def client(monkeypatch, speakers, failing_langs):
    from services.tts import app as tts_app

    def load(voice, device):
        if voice.lang in failing_langs:
            raise RuntimeError(f"{voice.lang} voice file is corrupt")
        return speakers.setdefault(voice.lang, FakeSpeaker())

    monkeypatch.setattr(tts_app, "_load_speaker", load)
    with TestClient(tts_app.app) as test_client:
        yield test_client
