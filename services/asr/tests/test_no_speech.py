"""Whisper large-v3-turbo transcribes non-speech as a courtesy phrase (#498).

Its no-speech token never wins, even on digital silence, so the service has to
decide from the audio itself that a recording holds no speech. An empty
transcript then lets the gateway answer 422 NO_SPEECH_RECOGNIZED.
"""

import struct
import wave
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from services.asr import app as asr_app
from services.asr.app import app

client = TestClient(app)
SAMPLE_WAV = Path(__file__).with_name("sample.wav")
HALLUCINATION = " Vielen Dank."


class _HallucinatingModel:
    def __init__(self):
        self.calls = 0

    def transcribe(self, _path, language="de"):
        self.calls += 1
        return {"text": HALLUCINATION}


@pytest.fixture
def model(monkeypatch):
    fake = _HallucinatingModel()
    monkeypatch.setattr(asr_app, "model", fake)
    # Normalisation is ffmpeg's job, and CI has no ffmpeg; the clips are already 16 kHz mono.
    monkeypatch.setattr(asr_app, "normalize_to_wav16k", _copy_of)
    return fake


def _copy_of(path):
    copy = Path(path).with_suffix(".norm.wav")
    copy.write_bytes(Path(path).read_bytes())
    return str(copy)


def _write_wav(path, samples, rate=16000):
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm.tobytes())
    return path


def _read_sample(seconds=None, gain_db=0.0):
    with wave.open(str(SAMPLE_WAV)) as wav:
        rate = wav.getframerate()
        frames = wav.readframes(-1 if seconds is None else int(rate * seconds))
    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32767
    return samples * 10 ** (gain_db / 20), rate


def _transcribe(path, lang="de"):
    with Path(path).open("rb") as f:
        return client.post(
            "/transcribe", files={"file": ("clip.wav", f, "audio/wav")}, data={"lang": lang}
        )


def _tone(seconds, freqs, amplitude):
    t = np.arange(int(16000 * seconds)) / 16000
    return sum(amplitude * np.sin(2 * np.pi * f * t) for f in freqs)


@pytest.mark.parametrize("seconds", [0.5, 1, 3])
def test_digital_silence_answers_an_empty_transcript_without_running_whisper(
    tmp_path, model, seconds
):
    clip = _write_wav(tmp_path / "silence.wav", np.zeros(int(16000 * seconds)))

    response = _transcribe(clip)

    assert response.status_code == 200
    assert response.json() == {"text": "", "fallback": False}
    assert model.calls == 0


def test_noise_below_the_gateway_gate_answers_an_empty_transcript(tmp_path, model):
    # Production measured " Vielen Dank." for ±30 LSB of noise (#498).
    lsb = np.resize(np.array([30, -30, 12, -7, 25, -18], dtype=np.float32) / 32767, 16000)
    clip = _write_wav(tmp_path / "low-noise.wav", lsb)

    assert _transcribe(clip).json()["text"] == ""
    assert model.calls == 0


@pytest.mark.parametrize(
    "freqs", [(50, 100, 150), (230, 470, 910, 1830, 3170)], ids=["mains-hum", "fan"]
)
def test_a_steady_background_sound_answers_an_empty_transcript(tmp_path, model, freqs):
    clip = _write_wav(tmp_path / "steady.wav", _tone(3, freqs, 0.05))

    assert _transcribe(clip, lang="en").json()["text"] == ""
    assert model.calls == 0


@pytest.mark.parametrize(
    ("seconds", "gain_db"),
    [(None, 0.0), (1.5, 0.0), (None, -15.0)],
    ids=["full-recording", "one-word", "quiet-speaker"],
)
def test_speech_still_reaches_whisper(tmp_path, model, seconds, gain_db):
    samples, rate = _read_sample(seconds, gain_db)
    clip = _write_wav(tmp_path / "speech.wav", samples, rate)

    assert _transcribe(clip).json()["text"] == HALLUCINATION
    assert model.calls == 1


@pytest.mark.parametrize("seconds", [0.4, 0.6])
def test_a_short_word_over_steady_background_noise_still_reaches_whisper(tmp_path, model, seconds):
    # The word fills the whole clip, so the clip holds no noise-only stretch to
    # compare it against; the background sits 6 dB below the speech.
    speech, rate = _read_sample()
    onset = int(np.argmax(np.abs(speech) > 0.02))
    word = speech[onset : onset + int(rate * seconds)]
    t = np.arange(len(word)) / rate
    fan = sum(np.sin(2 * np.pi * f * t) for f in (230, 470, 910, 1830, 3170))
    fan *= np.sqrt(np.mean(word**2) / np.mean(fan**2)) / 2
    clip = _write_wav(tmp_path / "noisy-word.wav", word + fan, rate)

    assert _transcribe(clip).json()["text"] == HALLUCINATION
    assert model.calls == 1


def test_a_short_word_in_a_long_silence_still_reaches_whisper(tmp_path, model):
    speech, rate = _read_sample()
    onset = int(np.argmax(np.abs(speech) > 0.02))
    padded = np.zeros(rate * 6, dtype=np.float32)
    padded[rate * 2 : rate * 2 + int(rate * 0.2)] = speech[onset : onset + int(rate * 0.2)]
    clip = _write_wav(tmp_path / "word-in-silence.wav", padded, rate)

    assert _transcribe(clip).json()["text"] == HALLUCINATION
    assert model.calls == 1


def _raw_wav(rate, claimed_data_bytes, payload):
    fmt = struct.pack("<HHIIHH", 1, 1, rate, rate * 2, 2, 16)
    body = (
        b"WAVE"
        + b"fmt "
        + struct.pack("<I", len(fmt))
        + fmt
        + b"data"
        + struct.pack("<I", claimed_data_bytes)
        + payload
    )
    return b"RIFF" + struct.pack("<I", len(body)) + body


@pytest.mark.parametrize(
    "content",
    [b"not a wav file", _raw_wav(0, 4000, b"\x10\x00" * 2000)],
    ids=["not-a-wav", "zero-sample-rate"],
)
def test_a_recording_the_check_cannot_read_still_reaches_whisper(tmp_path, model, content):
    clip = tmp_path / "unreadable.wav"
    clip.write_bytes(content)

    assert _transcribe(clip).json()["text"] == HALLUCINATION
    assert model.calls == 1


def test_speech_cut_off_mid_sample_still_reaches_whisper(tmp_path, model):
    speech, rate = _read_sample(seconds=2)
    pcm = (speech * 32767).astype(np.int16).tobytes() + b"\x10"
    clip = tmp_path / "truncated.wav"
    clip.write_bytes(_raw_wav(rate, len(pcm) + 1000, pcm))

    response = _transcribe(clip)

    assert response.status_code == 200
    assert response.json()["text"] == HALLUCINATION
