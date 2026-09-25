import pytest

LANGS = {"de", "en", "ar", "tr", "ru", "uk", "am", "ti", "ku", "fa"}


def test_health_reports_every_voice_and_its_device(client):
    data = client.get("/health").json()
    assert data["status"] == "ok"
    assert data["model"] is True
    assert data["gpu_used"] is True
    assert set(data["voices"]) == LANGS
    assert data["voices"]["de"] == {
        "engine": "piper",
        "voice": "piper:de_DE-thorsten-high",
        "loaded": True,
        "device": "cuda",
        "error": None,
    }
    assert data["voices"]["am"]["engine"] == "mms"
    assert data["loaded_models"] == {lang: True for lang in LANGS}
    assert "resources" in data
    assert "autoscaling" in data


@pytest.mark.parametrize("failing_langs", [{"fa"}])
def test_one_failed_voice_degrades_health_and_says_why(client, failing_langs):
    data = client.get("/health").json()
    assert data["status"] == "degraded"
    assert data["voices"]["fa"]["loaded"] is False
    assert data["voices"]["fa"]["device"] is None
    assert "voice file is corrupt" in data["voices"]["fa"]["error"]
    assert data["voices"]["de"]["loaded"] is True


def test_voices_on_cpu_are_not_reported_as_gpu(client, speakers):
    for speaker in speakers.values():
        speaker.device = "cpu"
    assert client.get("/health").json()["gpu_used"] is False


def test_supported_languages_are_the_voice_table(client):
    assert client.get("/supported-languages").json() == {
        "languages": ["am", "ar", "de", "en", "fa", "ku", "ru", "ti", "tr", "uk"]
    }
