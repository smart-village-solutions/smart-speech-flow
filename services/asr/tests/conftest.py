import contextlib
import sys
import types


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
    fake_torch.device = getattr(fake_torch, "device", lambda name: name)
    fake_torch.float16 = getattr(fake_torch, "float16", "float16")
    fake_torch.float32 = getattr(fake_torch, "float32", "float32")
    fake_torch.inference_mode = getattr(
        fake_torch, "inference_mode", contextlib.nullcontext
    )
    fake_torch.manual_seed = getattr(fake_torch, "manual_seed", lambda _seed: None)


def _install_fake_whisper() -> None:
    if "whisper" in sys.modules:
        return

    class _FakeWhisperModel:
        def transcribe(self, _path, language="de"):
            return {"text": f"dummy transcription in {language}"}

    fake_whisper = types.ModuleType("whisper")
    fake_whisper.load_model = lambda *_args, **_kwargs: _FakeWhisperModel()
    sys.modules["whisper"] = fake_whisper


_install_fake_torch()
_install_fake_whisper()
