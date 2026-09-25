import json
import sys
import types

import numpy as np
import pytest

from services.tts import piper_engine
from services.tts.speech_text import UnspeakableTextError


class FakeSession:
    def __init__(self, path, sess_options=None, providers=None):
        self.path, self.providers = path, providers

    def get_providers(self):
        return FakeOrt.active_providers


class FakeOrt(types.ModuleType):
    active_providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    InferenceSession = FakeSession
    SessionOptions = object


class FakeChunk:
    def __init__(self, samples):
        self.audio_float_array = np.array(samples, dtype=np.float32)


class FakeVoice:
    def __init__(self, session, config):
        self.session, self.config = session, config
        self.tashkeel_diacritizier = None
        self.chunks = [FakeChunk([0.1, 0.2]), FakeChunk([0.3])]

    def synthesize(self, text):
        return iter(self.chunks)


class FakeConfig:
    def __init__(self, espeak_voice, sample_rate):
        self.espeak_voice, self.sample_rate = espeak_voice, sample_rate

    @staticmethod
    def from_dict(data):
        return FakeConfig(data["espeak"]["voice"], data["audio"]["sample_rate"])


@pytest.fixture
def tashkeel(monkeypatch):
    FakeOrt.active_providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    tashkeel = types.ModuleType("piper.tashkeel")
    tashkeel.InferenceSession = None

    class Diacritizer:
        def __init__(self):
            self.session = tashkeel.InferenceSession("tashkeel/model.onnx")

    tashkeel.TashkeelDiacritizer = Diacritizer
    piper = types.ModuleType("piper")
    piper.PiperVoice = FakeVoice
    piper.tashkeel = tashkeel
    config = types.ModuleType("piper.config")
    config.PiperConfig = FakeConfig
    monkeypatch.setitem(sys.modules, "onnxruntime", FakeOrt("onnxruntime"))
    monkeypatch.setitem(sys.modules, "piper", piper)
    monkeypatch.setitem(sys.modules, "piper.config", config)
    monkeypatch.setitem(sys.modules, "piper.tashkeel", tashkeel)
    return tashkeel


def _voice_dir(tmp_path, espeak_voice="de"):
    (tmp_path / "model.onnx").write_bytes(b"onnx")
    (tmp_path / "model.onnx.json").write_text(
        json.dumps({"espeak": {"voice": espeak_voice}, "audio": {"sample_rate": 22050}})
    )
    return tmp_path


def test_cuda_sessions_use_heuristic_conv_search_and_a_tight_arena():
    ((name, options),) = piper_engine.providers_for("cuda")
    assert name == "CUDAExecutionProvider"
    assert options["cudnn_conv_algo_search"] == "HEURISTIC"
    assert options["arena_extend_strategy"] == "kSameAsRequested"


def test_a_voice_that_did_not_get_cuda_refuses_to_load(tashkeel, tmp_path):
    FakeOrt.active_providers = ["CPUExecutionProvider"]
    with pytest.raises(piper_engine.VoiceUnavailableError, match="CPUExecutionProvider"):
        piper_engine.load_piper_speaker(_voice_dir(tmp_path), "cuda")


def test_cpu_device_is_allowed_to_run_on_cpu(tashkeel, tmp_path):
    FakeOrt.active_providers = ["CPUExecutionProvider"]
    speaker = piper_engine.load_piper_speaker(_voice_dir(tmp_path), "cpu")
    assert speaker.device == "cpu"


def test_synthesis_concatenates_sentence_chunks(tashkeel, tmp_path):
    speaker = piper_engine.load_piper_speaker(_voice_dir(tmp_path), "cuda")
    audio, rate = speaker.synthesize("Hallo. Welt.", seed=1)
    assert rate == 22050
    assert audio.tolist() == pytest.approx([0.1, 0.2, 0.3])


def test_text_that_yields_no_audio_is_unspeakable(tashkeel, tmp_path):
    speaker = piper_engine.load_piper_speaker(_voice_dir(tmp_path), "cuda")
    speaker._voice.chunks = []
    with pytest.raises(UnspeakableTextError):
        speaker.synthesize("…", seed=1)


def test_non_arabic_voices_leave_the_diacritizer_alone(tashkeel, tmp_path):
    speaker = piper_engine.load_piper_speaker(_voice_dir(tmp_path, "de"), "cuda")
    assert speaker._voice.tashkeel_diacritizier is None


def test_arabic_diacritizer_gets_explicit_providers(tashkeel, tmp_path):
    speaker = piper_engine.load_piper_speaker(_voice_dir(tmp_path, "ar"), "cuda")
    diacritizer_session = speaker._voice.tashkeel_diacritizier.session
    assert diacritizer_session.providers == piper_engine.providers_for("cuda")
    assert tashkeel.InferenceSession is None
