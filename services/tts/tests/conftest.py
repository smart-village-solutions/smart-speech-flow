import io
import sys
import types

import numpy as np


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
        payload = b"RIFFfakeWAVEfmt " + bytes(str(sampling_rate), "ascii")
        if isinstance(target, io.BytesIO):
            target.write(payload)
            return
        target.write(payload)

    fake_soundfile = types.ModuleType("soundfile")
    fake_soundfile.write = _write
    sys.modules["soundfile"] = fake_soundfile


def _install_fake_transformers() -> None:
    fake_transformers = sys.modules.get("transformers")
    if fake_transformers is None:
        fake_transformers = types.ModuleType("transformers")
        sys.modules["transformers"] = fake_transformers

    class _FakePipeline:
        def __call__(self, _text):
            return {
                "audio": np.array([[0.1, -0.1, 0.0, 0.2]], dtype=np.float32),
                "sampling_rate": 16000,
            }

    fake_transformers.pipeline = lambda *_args, **_kwargs: _FakePipeline()
    fake_transformers.M2M100ForConditionalGeneration = getattr(
        fake_transformers, "M2M100ForConditionalGeneration", None
    )
    fake_transformers.M2M100Tokenizer = getattr(
        fake_transformers, "M2M100Tokenizer", None
    )


_install_fake_torch()
_install_fake_soundfile()
_install_fake_transformers()
