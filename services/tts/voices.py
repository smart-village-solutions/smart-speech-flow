"""The one voice each product language is spoken with, pinned to exact files.

Standard library only: the image's build stage imports this to download the
voices before any dependency is installed.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_PIPER_REVISION = "c10ece1aade47bb51c153c893d14e5bf8e5b7117"
_HF = "https://huggingface.co"


@dataclass(frozen=True)
class VoiceFile:
    name: str
    url: str
    sha256: str


@dataclass(frozen=True)
class Voice:
    lang: str
    engine: Literal["piper", "mms"]
    name: str
    files: tuple[VoiceFile, ...]
    spell_numbers: bool


def _piper(lang: str, voice_id: str, model_sha256: str, config_sha256: str) -> Voice:
    locale, speaker, quality = voice_id.split("-")
    base = (
        f"{_HF}/rhasspy/piper-voices/resolve/{_PIPER_REVISION}/"
        f"{locale.split('_')[0]}/{locale}/{speaker}/{quality}/{voice_id}"
    )
    return Voice(
        lang=lang,
        engine="piper",
        name=f"piper:{voice_id}",
        files=(
            VoiceFile("model.onnx", f"{base}.onnx", model_sha256),
            VoiceFile("model.onnx.json", f"{base}.onnx.json", config_sha256),
        ),
        spell_numbers=False,
    )


def _mms(lang: str, repo: str, revision: str, hashes: dict[str, str]) -> Voice:
    return Voice(
        lang=lang,
        engine="mms",
        name=repo,
        files=tuple(
            VoiceFile(name, f"{_HF}/{repo}/resolve/{revision}/{name}", sha256)
            for name, sha256 in hashes.items()
        ),
        spell_numbers=True,
    )


VOICES = {
    voice.lang: voice
    for voice in (
        _piper(
            "de",
            "de_DE-thorsten-high",
            "9df1c43c61149ef9b39e618e2b861fbe41e1fcea9390b2dac62e8761573ea4f1",
            "6de734444e4c3f9e33b7ebe2746dbc19b71e85f613e79c65acf623200b99a76a",
        ),
        _piper(
            "en",
            "en_US-ljspeech-high",
            "5d4f08ba6a2a48c44592eed3ce56bf85e9de3dd4e20df90541ae68a8310c029a",
            "7e1f4634af596d83cca997fb7a931ba80b70f8a316a2655ee69c55365e0ace14",
        ),
        _piper(
            "tr",
            "tr_TR-dfki-medium",
            "2844717f524ab965d3fe86e60562cbb601d3e456836efcc2196cc3a14112a8fb",
            "13ebd7810f1b61b5027583cf3131a0a233b6ea81c38f2200ebc4ff41c3cca039",
        ),
        _piper(
            "ru",
            "ru_RU-denis-medium",
            "15fab56e11a097858ee115545d0f697fc2a316c41a291a5362349fb870411b0a",
            "831c860dac0b5073eaa81610a0a638ec23d90a6cf8e5f871b4485c2cec3767c8",
        ),
        _piper(
            "uk",
            "uk_UA-tetiana-high",
            "1206d8447b99632badeb63d6132241f76cf551874e5254eb8836db36aed7c85c",
            "c96a051028976afc74269f73470651384deb6872431f890cad3b6424d09e812b",
        ),
        _piper(
            "ar",
            "ar_JO-kareem-medium",
            "9e95cab07b679da603bba17c4dec7ab3111320571964ee95c0379603c086491e",
            "ea6d9b9d9076dbdb6bf5c98c6a141ef154959d2359709b37855727964e7d6c4d",
        ),
        _piper(
            "fa",
            "fa_IR-gyro-medium",
            "37dfae43c82ee38ca9e6aac4ffef76a74d6b282ccbc397b27761f35d355c99ba",
            "4cd0ca01824b460f490224e284f9b68ecf07f91f3c654ba3bce59d4eb7646082",
        ),
        _piper(
            "ku",
            "ku_TR-berfin_renas-medium",
            "bc0b2cf086f9a33ca1d7ca2ca80b6f35f8917d0c89afe4a645c5b9d56ac355c4",
            "66d0da87aa8e572c7e6ee67647aa6af6008e85e38819679f17dc9b86e3affca8",
        ),
        _mms(
            "am",
            "facebook/mms-tts-amh",
            "e366aee5e22a72b9a3333e081ddafb234538d9bb",
            {
                "config.json": "cf0952ec63a9038e85fed0a0126fd9a1c5309abc9d39760442400d50a3768d25",
                "model.safetensors": (
                    "2eb3bba0c0efb6260a71dbe753855388ff2bf9d98ea09996c23e0721a0662954"
                ),
                "special_tokens_map.json": (
                    "72b32fc2b52231306209a03cae6d1f1563b732e6184ffa4a414f6bb18f38d3ab"
                ),
                "tokenizer_config.json": (
                    "4dd1eadcae389def443ecce4db0356300dc337a48990ac9d423c8568c5f489f3"
                ),
                "vocab.json": "8b1991a22048d0ddb437c0a4361a1d3a13f72846cafaba6b4cdc6dae4d33da8b",
            },
        ),
        _mms(
            "ti",
            "facebook/mms-tts-tir",
            "cd216946d4d313dc9083f492d9e7dba151dbd90e",
            {
                "config.json": "dea2b227ff3c02a13b4f75dc25d3d693c7d047beb77f7b17bdeb6234ddcf9123",
                "model.safetensors": (
                    "19a3dd1a9d2f40028d99cd3742d766a0924ee208dad309de4d2ca3eb6361be6f"
                ),
                "special_tokens_map.json": (
                    "7a1cc941d7ea26ad0a9f78e166a97a76b21de2f09e320e3b564bf2e22c5d85c4"
                ),
                "tokenizer_config.json": (
                    "cf6fdbc91183488ecd6189e2820580af1753954f40d0966a9582337bb365a20a"
                ),
                "vocab.json": "a07287509379fb6a2337f2342f4abd9602c42fa42ead319d2fedf748ce162504",
            },
        ),
    )
}


def voice_root() -> Path:
    return Path(os.environ.get("TTS_VOICE_DIR", "/opt/tts-voices"))


def voice_dir(voice: Voice) -> Path:
    return voice_root() / voice.lang
