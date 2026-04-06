import contextlib
import sys
import types


def _install_fake_torch() -> None:
    fake_torch = sys.modules.get("torch")
    if fake_torch is None:
        fake_torch = types.ModuleType("torch")
        sys.modules["torch"] = fake_torch

    class _FakeTensor:
        def __init__(self, values):
            self.values = values
            self.shape = (1, len(values))

        def to(self, _device):
            return self

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

    class _FakeDevice:
        def __init__(self, name):
            self.type = str(name).split(":")[0]
            self.name = str(name)

        def __str__(self):
            return self.name

    fake_torch.cuda = _FakeCuda()
    fake_torch.float16 = "float16"
    fake_torch.float32 = "float32"
    fake_torch.device = lambda name: _FakeDevice(name)
    fake_torch.inference_mode = contextlib.nullcontext
    fake_torch.Tensor = _FakeTensor
    fake_torch.manual_seed = getattr(fake_torch, "manual_seed", lambda _seed: None)


def _install_fake_transformers() -> None:
    fake_transformers = sys.modules.get("transformers")
    if fake_transformers is None:
        fake_transformers = types.ModuleType("transformers")
        sys.modules["transformers"] = fake_transformers

    class _FakeTensor:
        def __init__(self, values):
            self.values = values
            self.shape = (1, len(values))

        def to(self, _device):
            return self

    class _FakeTokenizer:
        lang_code_to_id = {"de": 0, "en": 1, "ar": 2, "tr": 3}

        @classmethod
        def from_pretrained(cls, _name):
            return cls()

        def __call__(self, _text, **_kwargs):
            return {"input_ids": _FakeTensor([1, 2, 3])}

        def get_lang_id(self, lang):
            return self.lang_code_to_id[lang]

        def batch_decode(self, _outputs, skip_special_tokens=True):
            return ["translated text"]

    class _FakeModel:
        @classmethod
        def from_pretrained(cls, _name, torch_dtype=None):
            return cls()

        def to(self, _device):
            return self

        def eval(self):
            return self

        def generate(self, **_kwargs):
            return _FakeTensor([10, 11, 12, 13])

    fake_transformers.M2M100ForConditionalGeneration = _FakeModel
    fake_transformers.M2M100Tokenizer = _FakeTokenizer
    fake_transformers.pipeline = getattr(
        fake_transformers, "pipeline", lambda *_args, **_kwargs: None
    )


_install_fake_torch()
_install_fake_transformers()
