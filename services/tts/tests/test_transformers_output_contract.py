import numpy as np
import pytest

from services.tts.app import _extract_audio_payload


def test_extract_audio_payload_from_dict_preserves_sampling_rate():
    audio = np.array([0.1, -0.1], dtype=np.float32)

    extracted_audio, sampling_rate = _extract_audio_payload(
        {"audio": audio, "sampling_rate": 22050}
    )

    assert extracted_audio is audio
    assert sampling_rate == 22050


def test_extract_audio_payload_from_list_preserves_sampling_rate():
    audio = np.array([0.2, 0.0], dtype=np.float32)

    extracted_audio, sampling_rate = _extract_audio_payload(
        [{"audio": audio, "sampling_rate": 24000}]
    )

    assert extracted_audio is audio
    assert sampling_rate == 24000


def test_extract_audio_payload_defaults_sampling_rate_when_missing():
    audio = np.array([0.3], dtype=np.float32)

    extracted_audio, sampling_rate = _extract_audio_payload({"audio": audio})

    assert extracted_audio is audio
    assert sampling_rate == 16000


@pytest.mark.parametrize("invalid_result", [None, [], "unexpected-output"])
def test_extract_audio_payload_rejects_unsupported_formats(invalid_result):
    with pytest.raises(TypeError):
        _extract_audio_payload(invalid_result)
