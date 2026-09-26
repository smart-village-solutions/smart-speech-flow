import contextlib
import sys
import types

import numpy as np
import pytest

from services.tts import mms_engine
from services.tts.mms_engine import has_speakable_tokens
from services.tts.speech_text import UnspeakableTextError


def test_a_sequence_of_only_padding_is_not_speakable():
    assert has_speakable_tokens([0, 0, 0], pad_id=0) is False
    assert has_speakable_tokens([], pad_id=0) is False


def test_one_real_token_is_speakable():
    assert has_speakable_tokens([0, 13, 0], pad_id=0) is True


def test_without_a_pad_id_any_token_counts():
    assert has_speakable_tokens([0], pad_id=None) is True


class _Tensor:
    def __init__(self, values):
        self.values = values

    def __getitem__(self, index):
        return _Tensor(self.values[index])

    def tolist(self):
        return list(self.values)

    def to(self, device):
        return self

    def float(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return np.array(self.values, dtype=np.float32)


class _Tokenizer:
    pad_token_id = 0
    is_uroman = True

    def __init__(self, ids):
        self.ids = ids
        self.texts = []

    def __call__(self, text, return_tensors):
        self.texts.append(text)
        return {"input_ids": _Tensor([self.ids])}


class _Romanizer:
    def romanize_string(self, text):
        return f"roman({text})"


class _Model:
    def __init__(self):
        self.calls = 0

    def __call__(self, **inputs):
        self.calls += 1
        return types.SimpleNamespace(waveform=_Tensor([[0.5, -0.5]]))


class _Torch:
    def __init__(self):
        self.seeds = []

    def manual_seed(self, seed):
        self.seeds.append(seed)

    def inference_mode(self):
        return contextlib.nullcontext()


def _speaker(ids):
    speaker = object.__new__(mms_engine.MmsSpeaker)
    speaker._torch, speaker._tokenizer, speaker._model = _Torch(), _Tokenizer(ids), _Model()
    speaker._romanizer = _Romanizer()
    speaker.device, speaker.sample_rate = "cpu", 16000
    return speaker


def test_synthesis_is_seeded_and_returns_float_audio():
    speaker = _speaker([0, 5, 0])
    audio, rate = speaker.synthesize("ሰላም", seed=3)
    assert rate == 16000
    assert audio.tolist() == [0.5, -0.5]
    assert speaker._torch.seeds == [3]


def test_text_is_romanized_once_by_the_cached_romanizer():
    speaker = _speaker([0, 5, 0])
    speaker.synthesize("ሰላም", seed=3)
    assert speaker._tokenizer.texts == ["roman(ሰላም)"]


def test_unspeakable_text_raises_before_the_model_runs():
    speaker = _speaker([0, 0])
    with pytest.raises(UnspeakableTextError):
        speaker.synthesize("…", seed=3)
    assert speaker._model.calls == 0


def test_loading_puts_the_model_on_the_device_in_eval_mode(monkeypatch, tmp_path):
    loaded = {}

    class FakeVits:
        config = types.SimpleNamespace(sampling_rate=16000)

        @classmethod
        def from_pretrained(cls, directory):
            loaded["model_dir"] = directory
            return cls()

        def to(self, device):
            loaded["device"] = device
            return self

        def eval(self):
            loaded["eval"] = True
            return self

    class FakeAutoTokenizer:
        @staticmethod
        def from_pretrained(directory):
            loaded["tokenizer_dir"] = directory
            return _Tokenizer([0, 5])

    transformers = types.ModuleType("transformers")
    transformers.VitsModel = FakeVits
    transformers.AutoTokenizer = FakeAutoTokenizer
    monkeypatch.setitem(sys.modules, "transformers", transformers)
    uroman = types.ModuleType("uroman")
    uroman.Uroman = _Romanizer
    monkeypatch.setitem(sys.modules, "uroman", uroman)

    speaker = mms_engine.MmsSpeaker(tmp_path, "cuda")

    assert loaded == {
        "tokenizer_dir": tmp_path,
        "model_dir": tmp_path,
        "device": "cuda",
        "eval": True,
    }
    assert speaker.device == "cuda"
    assert speaker.sample_rate == 16000
    assert isinstance(speaker._romanizer, _Romanizer)
