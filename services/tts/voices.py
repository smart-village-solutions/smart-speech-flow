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
            "it",
            "it_IT-serena-medium",
            "fe4e26b2c1236e2a44d2e295cad564d94a0d8b0a9fca1ccdfd70dd4af3116eb5",
            "14cb4995874138b2792ae07753b5540942124761af9ae6609f9b520f28837881",
        ),
        _piper(
            "ro",
            "ro_RO-mihai-medium",
            "e0608bbbd53c80267c09ece681b09f5199f54e792356684c8073738e5f15d29f",
            "8cc0c9f077dc0cec3c25a6a055ec8046db8e40a2510591582f2c9c869f4bc47e",
        ),
        _piper(
            "pl",
            "pl_PL-gosia-medium",
            "38f66464240ed74f186e6b7dc13c6e3b22e023426299f25c2b3cc9dfa9373fbc",
            "1aefb31a9d53ffe44a8163ff73ec833acb7a6253848f6bb0403d8a66f9c7510d",
        ),
        _piper(
            "bg",
            "bg_BG-dimitar-medium",
            "4972fe764468e8501416407ad81662de94cc6c9cdc680fcf807daef04e319f13",
            "ec9a9abdd17384d3db225e83085b2f68b790b112f058417c3a8a2ac58b79e7f0",
        ),
        _piper(
            "el",
            "el_GR-joy-medium",
            "31b1d51dc72dd43a5429b67798e27599f8cdcfce8a80265bc6f50d932bf144bc",
            "451a8885a0ea72e4432fffe22e65a75bbd2e65f6757273d1a5a9ed8a3419852e",
        ),
        _piper(
            "fr",
            "fr_FR-siwis-medium",
            "641d1ab097da2b81128c076810edb052b385decc8be3381814802a64a73baf99",
            "39479916c2db192b5ac9764daddd0c744d83e023ad890c6976c0633ae4df8959",
        ),
        _piper(
            "es",
            "es_ES-davefx-medium",
            "6658b03b1a6c316ee4c265a9896abc1393353c2d9e1bca7d66c2c442e222a917",
            "0e0dda87c732f6f38771ff274a6380d9252f327dca77aa2963d5fbdf9ec54842",
        ),
        _piper(
            "pt",
            "pt_BR-faber-medium",
            "858555e3a064209c57088fe6bd70c4c3dc54d03eaa00c45d5ecaf43a33f95aa7",
            "7e694de195ae3fc36dd732c445eb04fb49b649854893cb5506b978f0d50a1d6f",
        ),
        _piper(
            "sq",
            "sq_AL-edon-medium",
            "5d0ae8af36a00ac6813517b2af47bc4cda42e88ece04f6076ae3b0f5479c57c8",
            "e9ee77beea52d8042bca589448bb48033ac0f7c1d86daee84ad1d5692d1270f7",
        ),
        _piper(
            "hu",
            "hu_HU-imre-medium",
            "af7d98e2031b4f00cf3693cafc47b0b5347f23c28cd6a5957a693f76d7202c2d",
            "bb9c31dd8429b1414d486e5d52d52f0790949c63bfaf1345075d42e23ad10c83",
        ),
        _piper(
            "zh",
            "zh_CN-huayan-medium",
            "9929917bf8cabb26fd528ea44d3a6699c11e87317a14765312420be230be0f3d",
            "d521dc45504a8ccc99e325822b35946dd701840bfb07e3dbb31a40929ed6a82b",
        ),
        _piper(
            "hi",
            "hi_IN-priyamvada-medium",
            "aa63bcf2cd493b55a450f280e23cf77f03afc9af7015e6e5acd43b652f166c88",
            "5efc0ccf7529f3528996d46e0fac1f969f681d44a8e55bfa6236ff8841b5d52d",
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
    )
}


def voice_root() -> Path:
    return Path(os.environ.get("TTS_VOICE_DIR", "/opt/tts-voices"))


def voice_dir(voice: Voice) -> Path:
    return voice_root() / voice.lang
