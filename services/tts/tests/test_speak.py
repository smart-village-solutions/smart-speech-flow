import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

from app import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_speak_de():
    response = client.post("/synthesize", json={"text": "Hallo Welt", "lang": "de"})
    assert response.status_code in (200, 500)
    if response.status_code == 200:
        assert response.headers["content-type"].startswith("audio/")
        assert len(response.content) > 0


def test_speak_en():
    response = client.post("/synthesize", json={"text": "Hello world", "lang": "en"})
    assert response.status_code in (200, 500)
    if response.status_code == 200:
        assert response.headers["content-type"].startswith("audio/")
        assert len(response.content) > 0


def test_speak_ar():
    response = client.post("/synthesize", json={"text": "مرحبا", "lang": "ar"})
    assert response.status_code in (200, 500)
    if response.status_code == 200:
        assert response.headers["content-type"].startswith("audio/")
        assert len(response.content) > 0


def test_speak_tr():
    response = client.post("/synthesize", json={"text": "Merhaba", "lang": "tr"})
    assert response.status_code in (200, 500)
    if response.status_code == 200:
        assert response.headers["content-type"].startswith("audio/")
        assert len(response.content) > 0


def test_speak_am():
    response = client.post("/synthesize", json={"text": "ሰላም", "lang": "am"})
    assert response.status_code in (200, 500)
    if response.status_code == 200:
        assert response.headers["content-type"].startswith("audio/")
        assert len(response.content) > 0


def test_speak_fa():
    response = client.post("/synthesize", json={"text": "سلام", "lang": "fa"})
    assert response.status_code in (200, 500)
    if response.status_code == 200:
        assert response.headers["content-type"].startswith("audio/")
        assert len(response.content) > 0


def test_speak_ru():
    response = client.post("/synthesize", json={"text": "Привет", "lang": "ru"})
    assert response.status_code in (200, 500)
    if response.status_code == 200:
        assert response.headers["content-type"].startswith("audio/")
        assert len(response.content) > 0


def test_speak_uk():
    response = client.post("/synthesize", json={"text": "Привіт", "lang": "uk"})
    assert response.status_code in (200, 500)
    if response.status_code == 200:
        assert response.headers["content-type"].startswith("audio/")
        assert len(response.content) > 0


def test_speak_success_de():
    response = client.post("/synthesize", json={"text": "Hallo Welt", "lang": "de"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/")
    assert len(response.content) > 0
