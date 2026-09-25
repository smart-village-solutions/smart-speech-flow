import dataclasses
import hashlib
import io

import pytest

from services.tts import fetch_voices
from services.tts.voices import VOICES, voice_dir

PRODUCT_LANGUAGES = {"de", "en", "ar", "tr", "ru", "uk", "am", "ti", "ku", "fa"}


def test_every_product_language_has_exactly_one_voice():
    assert set(VOICES) == PRODUCT_LANGUAGES
    assert all(voice.lang == lang for lang, voice in VOICES.items())


def test_every_file_is_pinned_to_a_revision_and_a_hash():
    for voice in VOICES.values():
        assert voice.files
        for file in voice.files:
            assert "/resolve/main/" not in file.url
            assert len(file.sha256) == 64
            int(file.sha256, 16)


def test_only_mms_voices_need_numbers_spelled():
    assert {v.lang for v in VOICES.values() if v.engine == "mms"} == {"am", "ti"}
    assert all(v.spell_numbers == (v.engine == "mms") for v in VOICES.values())


def test_piper_urls_point_at_the_voice_they_name():
    voice = VOICES["de"]
    assert voice.name == "piper:de_DE-thorsten-high"
    assert {f.name for f in voice.files} == {"model.onnx", "model.onnx.json"}
    assert all("/de/de_DE/thorsten/high/de_DE-thorsten-high.onnx" in f.url for f in voice.files)


def test_voice_files_live_under_the_configured_root(monkeypatch, tmp_path):
    monkeypatch.setenv("TTS_VOICE_DIR", str(tmp_path))
    assert voice_dir(VOICES["de"]) == tmp_path / "de"


def _opener_serving(payloads):
    def opener(url, timeout):
        return io.BytesIO(payloads[url])

    return opener


def test_fetch_writes_files_whose_hash_matches(monkeypatch, tmp_path):
    voice = VOICES["de"]
    payloads = {f.url: f"payload {f.name}".encode() for f in voice.files}
    pinned = tuple(
        dataclasses.replace(f, sha256=hashlib.sha256(payloads[f.url]).hexdigest())
        for f in voice.files
    )
    monkeypatch.setattr(fetch_voices, "VOICES", {"de": dataclasses.replace(voice, files=pinned)})

    fetch_voices.fetch_all(tmp_path, opener=_opener_serving(payloads))

    for f in voice.files:
        assert (tmp_path / "de" / f.name).read_bytes() == payloads[f.url]


def _pinned_to(monkeypatch, payloads):
    voice = VOICES["de"]
    pinned = tuple(
        dataclasses.replace(f, sha256=hashlib.sha256(payloads[f.url]).hexdigest())
        for f in voice.files
    )
    monkeypatch.setattr(fetch_voices, "VOICES", {"de": dataclasses.replace(voice, files=pinned)})
    monkeypatch.setattr(fetch_voices.time, "sleep", lambda seconds: None)
    return voice


def test_fetch_retries_a_read_that_timed_out(monkeypatch, tmp_path):
    payloads = {f.url: f"payload {f.name}".encode() for f in VOICES["de"].files}
    voice = _pinned_to(monkeypatch, payloads)
    failures = {voice.files[0].url: 2}

    def flaky_opener(url, timeout):
        if failures.get(url):
            failures[url] -= 1
            raise TimeoutError("The read operation timed out")
        return io.BytesIO(payloads[url])

    fetch_voices.fetch_all(tmp_path, opener=flaky_opener)

    assert (tmp_path / "de" / voice.files[0].name).read_bytes() == payloads[voice.files[0].url]
    assert not list((tmp_path / "de").glob("*.part"))


def test_fetch_gives_up_after_the_last_attempt(monkeypatch, tmp_path):
    payloads = {f.url: b"x" for f in VOICES["de"].files}
    _pinned_to(monkeypatch, payloads)
    calls = []

    def dead_opener(url, timeout):
        calls.append(url)
        raise TimeoutError("The read operation timed out")

    with pytest.raises(TimeoutError):
        fetch_voices.fetch_all(tmp_path, opener=dead_opener)
    assert len(calls) == fetch_voices.ATTEMPTS


def test_fetch_refuses_a_file_whose_hash_differs(monkeypatch, tmp_path):
    voice = VOICES["de"]
    monkeypatch.setattr(fetch_voices, "VOICES", {"de": voice})
    opener = _opener_serving({f.url: b"tampered" for f in voice.files})

    with pytest.raises(fetch_voices.HashMismatchError):
        fetch_voices.fetch_all(tmp_path, opener=opener)
    assert not any((tmp_path / "de").glob("*"))
