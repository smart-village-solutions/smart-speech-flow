"""MMS voices for the languages Piper has none for (am, ti).

Loaded as a bare VitsModel rather than through transformers' pipeline, so the
device and the seed are ours. The tokenizer romanizes Ethiopic script itself.
Text with no in-vocabulary character tokenizes to padding only, which VITS
answers with a crash, so it is rejected first.
"""

from pathlib import Path
from typing import Any

import numpy as np

from services.tts.speech_text import UnspeakableTextError


def has_speakable_tokens(ids: list[int], pad_id: int | None) -> bool:
    if pad_id is None:
        return bool(ids)
    return any(token != pad_id for token in ids)


class MmsSpeaker:
    def __init__(self, directory: Path, device: str) -> None:
        import torch
        from transformers import AutoTokenizer, VitsModel

        self._torch: Any = torch
        self._tokenizer: Any = AutoTokenizer.from_pretrained(directory)
        self._model: Any = VitsModel.from_pretrained(directory).to(device).eval()
        self.device = device
        self.sample_rate = self._model.config.sampling_rate

    def synthesize(self, text: str, seed: int) -> tuple[np.ndarray, int]:
        inputs = self._tokenizer(text, return_tensors="pt")
        if not has_speakable_tokens(inputs["input_ids"][0].tolist(), self._tokenizer.pad_token_id):
            raise UnspeakableTextError(text)
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        self._torch.manual_seed(seed)
        with self._torch.inference_mode():
            waveform = self._model(**inputs).waveform[0]
        return waveform.float().cpu().numpy(), self.sample_rate
