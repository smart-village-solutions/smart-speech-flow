"""Piper voices on onnxruntime.

onnxruntime quietly falls back to CPU when the CUDA provider cannot start, so
a session is only accepted when the provider it actually got is the one asked
for. Piper's Arabic diacritizer builds its own session without naming
providers, which a GPU build of onnxruntime rejects, so it is built here with
explicit ones.
"""

import json
from pathlib import Path
from typing import Any

import numpy as np

from services.tts.speech_text import UnspeakableTextError


class VoiceUnavailableError(RuntimeError):
    pass


def providers_for(device: str) -> list[Any]:
    if device == "cuda":
        return [
            (
                "CUDAExecutionProvider",
                {
                    # The default exhaustive search re-runs for every new input length.
                    "cudnn_conv_algo_search": "HEURISTIC",
                    "arena_extend_strategy": "kSameAsRequested",
                },
            )
        ]
    return ["CPUExecutionProvider"]


def create_session(model_path: Path, device: str) -> Any:
    import onnxruntime

    session = onnxruntime.InferenceSession(
        str(model_path),
        sess_options=onnxruntime.SessionOptions(),
        providers=providers_for(device),
    )
    expected = "CUDAExecutionProvider" if device == "cuda" else "CPUExecutionProvider"
    active = session.get_providers()
    if not active or active[0] != expected:
        raise VoiceUnavailableError(f"{model_path} runs on {active}, expected {expected}")
    return session


class PiperSpeaker:
    def __init__(self, voice: Any, device: str) -> None:
        self._voice = voice
        self.device = device
        self.sample_rate = voice.config.sample_rate

    def synthesize(self, text: str, _seed: int) -> tuple[np.ndarray, int]:
        # Piper's noise is drawn inside the ONNX graph and cannot be seeded.
        chunks = [chunk.audio_float_array for chunk in self._voice.synthesize(text)]
        if not chunks:
            raise UnspeakableTextError(text)
        return np.concatenate(chunks), self.sample_rate


def load_piper_speaker(directory: Path, device: str) -> PiperSpeaker:
    from piper import PiperVoice
    from piper.config import PiperConfig

    config = PiperConfig.from_dict(json.loads((directory / "model.onnx.json").read_text()))
    voice = PiperVoice(session=create_session(directory / "model.onnx", device), config=config)
    if config.espeak_voice == "ar":
        voice.tashkeel_diacritizier = _arabic_diacritizer(device)
    return PiperSpeaker(voice, device)


def _arabic_diacritizer(device: str) -> Any:
    from piper import tashkeel

    original = tashkeel.InferenceSession
    tashkeel.InferenceSession = lambda path: create_session(Path(path), device)
    try:
        return tashkeel.TashkeelDiacritizer()
    finally:
        tashkeel.InferenceSession = original
