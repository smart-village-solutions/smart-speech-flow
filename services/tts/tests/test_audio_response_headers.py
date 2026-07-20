from services.tts.app import _audio_response


def test_audio_response_encodes_non_ascii_debug_info_in_headers():
    response = _audio_response(
        b"RIFFfake",
        "facebook/mms-tts-ara (MMS-TTS Fallback)",
        "ar",
        True,
        {"input": {"text": "مرحبا", "lang": "ar"}, "output": "audio/wav"},
    )

    assert response.headers["x-tts-model"] == "facebook/mms-tts-ara (MMS-TTS Fallback)"
    assert response.headers["x-tts-language"] == "ar"
    assert "\\u0645\\u0631\\u062d\\u0628\\u0627" in response.headers["x-debug-info"]
