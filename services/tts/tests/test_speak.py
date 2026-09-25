import pytest

from services.tts.speech_text import UnspeakableTextError

LANGS = ["de", "en", "ar", "tr", "ru", "uk", "am", "ti", "ku", "fa"]


@pytest.mark.parametrize("lang", LANGS)
def test_every_language_returns_wav(client, lang):
    response = client.post("/synthesize", json={"text": "Hallo", "lang": lang})
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["x-tts-fallback"] == "false"
    assert response.headers["x-tts-language"] == lang
    assert len(response.content) > 0


def test_model_header_names_the_voice_that_ran(client):
    response = client.post("/synthesize", json={"text": "Hallo", "lang": "de"})
    assert response.headers["x-tts-model"] == "piper:de_DE-thorsten-high"


def test_text_is_normalized_before_synthesis(client, speakers):
    client.post("/synthesize", json={"text": "Rufen Sie 0621 an, 3,50 €", "lang": "de"})
    assert speakers["de"].calls[-1][0] == "Rufen Sie 0 6 2 1 an, 3 Euro 50"


def test_mms_voices_get_numbers_spelled(client, speakers):
    client.post("/synthesize", json={"text": "15", "lang": "am"})
    assert speakers["am"].calls[-1][0] == "አስራ አምስት"


def test_romanized_tts_text_is_ignored(client, speakers):
    client.post("/synthesize", json={"text": "مرحبا", "tts_text": "mrhba", "lang": "ar"})
    assert speakers["ar"].calls[-1][0] == "مرحبا"


def test_language_codes_are_normalized(client, speakers):
    response = client.post("/synthesize", json={"text": "Hello", "lang": " EN "})
    assert response.status_code == 200
    assert speakers["en"].calls


def test_unknown_language_is_rejected(client):
    response = client.post("/synthesize", json={"text": "Hallo", "lang": "xx"})
    assert response.status_code == 400
    assert "xx" in response.json()["error"]


@pytest.mark.parametrize("text", ["  ", "", 42])
def test_empty_or_non_string_text_is_rejected(client, text):
    response = client.post("/synthesize", json={"text": text, "lang": "de"})
    assert response.status_code == 400


def test_unspeakable_text_is_a_client_error(client, speakers):
    def refuse(text, seed):
        raise UnspeakableTextError(text)

    speakers["uk"].synthesize = refuse
    response = client.post("/synthesize", json={"text": "OK", "lang": "uk"})
    assert response.status_code == 400
    assert "uk" in response.json()["error"]


@pytest.mark.parametrize("failing_langs", [{"fa"}])
def test_a_voice_that_failed_to_load_answers_503(client, failing_langs):
    response = client.post("/synthesize", json={"text": "سلام", "lang": "fa"})
    assert response.status_code == 503
    assert client.post("/synthesize", json={"text": "Hallo", "lang": "de"}).status_code == 200


def test_synthesis_failure_is_a_500(client, speakers):
    def explode(text, seed):
        raise RuntimeError("cuda gone")

    speakers["de"].synthesize = explode
    response = client.post("/synthesize", json={"text": "Hallo", "lang": "de"})
    assert response.status_code == 500
    assert "cuda gone" in response.json()["error"]


def test_session_id_seeds_the_voice(client, speakers):
    client.post("/synthesize", json={"text": "Hallo", "lang": "de", "session_id": "s-1"})
    client.post("/synthesize", json={"text": "Tschüss", "lang": "de", "session_id": "s-1"})
    first_seed, second_seed = (seed for _, seed in speakers["de"].calls)
    assert first_seed == second_seed


def test_debug_reports_the_spoken_text(client):
    response = client.post(
        "/synthesize", json={"text": "Zimmer 0621", "lang": "de", "debug": "true"}
    )
    assert "0 6 2 1" in response.headers["x-debug-info"]
