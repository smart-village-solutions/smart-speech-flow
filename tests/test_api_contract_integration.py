"""
API Contract Integration Tests
================================

Tests the public HTTP API endpoints to validate the API contract
as documented in docs/frontend_api.md.

These tests:
- Use real HTTP requests via FastAPI TestClient
- Validate response structure matches documentation
- Test with real backend services (ASR, Translation, TTS)
- Ensure API contract stability
"""

import pytest
import base64
import os
from pathlib import Path
from fastapi.testclient import TestClient
from services.api_gateway.app import app


@pytest.fixture
def client(monkeypatch):
    """
    FastAPI TestClient for making HTTP requests

    Monkeypatches service URLs to use localhost instead of Docker hostnames
    since TestClient runs outside the Docker network.
    """
    # Monkeypatch service URLs to use localhost (running outside Docker network)
    monkeypatch.setattr("services.api_gateway.pipeline_logic.ASR_URL", "http://localhost:8001/transcribe")
    monkeypatch.setattr("services.api_gateway.pipeline_logic.TRANSLATION_URL", "http://localhost:8002/translate")
    monkeypatch.setattr("services.api_gateway.pipeline_logic.TTS_URL", "http://localhost:8003/synthesize")

    return TestClient(app)


@pytest.fixture
def sample_audio_bytes():
    """Load real audio file from examples/ as bytes"""
    audio_path = Path(__file__).parent.parent / "examples" / "English_pcm.wav"
    with open(audio_path, "rb") as f:
        return f.read()


@pytest.fixture
def active_session(client):
    """Create and activate a test session"""
    # Admin creates session
    response = client.post("/api/admin/session/create")
    assert response.status_code == 201  # Created
    session_data = response.json()
    session_id = session_data["session_id"]

    # Customer activates session
    activate_response = client.post(
        "/api/customer/session/activate",
        json={
            "session_id": session_id,
            "customer_language": "en"
        }
    )
    assert activate_response.status_code == 200

    return session_id


class TestAudioMessageAPI:
    """Test audio message processing via HTTP API"""

    def test_audio_message_response_structure(self, client, active_session, sample_audio_bytes):
        """
        Test that POST /api/session/{sessionId}/message with audio
        returns the correct response structure as documented in frontend_api.md
        """
        session_id = active_session

        # Send audio message via API using multipart/form-data
        response = client.post(
            f"/api/session/{session_id}/message",
            files={"file": ("test_audio.wav", sample_audio_bytes, "audio/wav")},
            data={
                "source_lang": "en",
                "target_lang": "de",
                "client_type": "customer"
            }
        )

        # Verify HTTP status
        assert response.status_code == 200

        # Verify response structure matches frontend_api.md
        data = response.json()

        # Required fields from documentation
        assert "status" in data
        assert data["status"] == "success"

        assert "message_id" in data
        assert "session_id" in data
        assert data["session_id"] == session_id

        # Text fields - documented keys
        assert "original_text" in data  # ASR transcription
        assert "translated_text" in data  # ← Public API key (not translation_text!)
        assert isinstance(data["translated_text"], str)

        # Audio fields
        assert "audio_available" in data
        if data["audio_available"]:
            assert "audio_url" in data
            assert data["audio_url"].startswith("/api/audio/")

        # Metadata fields
        assert "processing_time_ms" in data
        assert isinstance(data["processing_time_ms"], (int, float))

        assert "pipeline_type" in data
        assert data["pipeline_type"] == "audio"

        assert "source_lang" in data
        assert data["source_lang"] == "en"

        assert "target_lang" in data
        assert data["target_lang"] == "de"

        assert "timestamp" in data

        # Pipeline metadata structure
        assert "pipeline_metadata" in data
        metadata = data["pipeline_metadata"]

        assert "input" in metadata
        assert metadata["input"]["type"] == "audio"
        assert metadata["input"]["source_lang"] == "en"

        assert "steps" in metadata
        assert len(metadata["steps"]) >= 3  # ASR, Translation, TTS minimum

        # Verify each step has required fields
        for step in metadata["steps"]:
            assert "name" in step
            assert "started_at" in step
            assert "completed_at" in step
            assert "duration_ms" in step

            # Each step should have input/output
            assert "input" in step
            assert "output" in step

    def test_audio_message_pipeline_metadata_steps(self, client, active_session, sample_audio_bytes):
        """
        Test that pipeline_metadata contains all expected processing steps
        for audio pipeline
        """
        session_id = active_session

        response = client.post(
            f"/api/session/{session_id}/message",
            files={"file": ("test_audio.wav", sample_audio_bytes, "audio/wav")},
            data={
                "source_lang": "en",
                "target_lang": "de",
                "client_type": "customer"
            }
        )

        assert response.status_code == 200
        data = response.json()

        metadata = data["pipeline_metadata"]
        step_names = [step["name"] for step in metadata["steps"]]

        # Audio pipeline should have: ASR -> Translation -> TTS
        assert "asr" in step_names or "ASR" in step_names
        assert "translation" in step_names or "Translation" in step_names
        assert "tts" in step_names or "TTS" in step_names


class TestTextMessageAPI:
    """Test text message processing via HTTP API"""

    def test_text_message_response_structure(self, client, active_session):
        """
        Test that POST /api/session/{sessionId}/message with text
        returns the correct response structure as documented in frontend_api.md
        """
        session_id = active_session

        # Send text message via API
        response = client.post(
            f"/api/session/{session_id}/message",
            json={
                "text": "Hello, how can I help you?",
                "source_lang": "en",
                "target_lang": "de",
                "client_type": "admin"
            }
        )

        # Verify HTTP status
        assert response.status_code == 200

        # Verify response structure matches frontend_api.md
        data = response.json()

        # Required fields from documentation
        assert "status" in data
        assert data["status"] == "success"

        assert "message_id" in data
        assert "session_id" in data

        # Text fields - documented keys
        assert "original_text" in data
        assert data["original_text"] == "Hello, how can I help you?"

        assert "translated_text" in data  # ← Public API key
        assert isinstance(data["translated_text"], str)
        assert len(data["translated_text"]) > 0

        # Audio fields
        assert "audio_available" in data
        if data["audio_available"]:
            assert "audio_url" in data

        # Metadata fields
        assert "processing_time_ms" in data
        assert "pipeline_type" in data
        assert data["pipeline_type"] == "text"

        assert "source_lang" in data
        assert data["source_lang"] == "en"

        assert "target_lang" in data
        assert data["target_lang"] == "de"

        assert "timestamp" in data

        # Pipeline metadata structure
        assert "pipeline_metadata" in data
        metadata = data["pipeline_metadata"]

        assert "input" in metadata
        assert metadata["input"]["type"] == "text"

        assert "steps" in metadata
        # Text pipeline: Translation -> TTS (no ASR)
        assert len(metadata["steps"]) >= 2

    def test_text_message_no_asr_step(self, client, active_session):
        """
        Test that text pipeline does NOT include ASR step
        """
        session_id = active_session

        response = client.post(
            f"/api/session/{session_id}/message",
            json={
                "text": "Good morning",
                "source_lang": "en",
                "target_lang": "de",
                "client_type": "customer"
            }
        )

        assert response.status_code == 200
        data = response.json()

        metadata = data["pipeline_metadata"]
        step_names = [step["name"].lower() for step in metadata["steps"]]

        # Text pipeline should NOT have ASR
        assert "asr" not in step_names

        # But should have Translation and TTS
        assert "translation" in step_names
        assert "tts" in step_names


class TestSessionAPI:
    """Test session management API endpoints"""

    def test_create_session_response_structure(self, client):
        """Test POST /api/admin/session/create response structure"""
        response = client.post("/api/admin/session/create")

        assert response.status_code == 201  # Created
        data = response.json()

        # Required fields from documentation
        assert "session_id" in data
        assert "client_url" in data
        assert "status" in data
        assert data["status"] == "pending"
        assert "created_at" in data
        assert "message" in data

    def test_get_session_status(self, client, active_session):
        """Test GET /api/session/{sessionId} response structure"""
        session_id = active_session

        response = client.get(f"/api/session/{session_id}")

        assert response.status_code == 200
        data = response.json()

        # Required fields from documentation
        assert "status" in data
        assert "customer_language" in data
        assert "admin_language" in data
        assert "message_count" in data
        assert "admin_connected" in data
        assert "customer_connected" in data

    def test_supported_languages_structure(self, client):
        """Test GET /api/languages/supported response structure"""
        response = client.get("/api/languages/supported")

        assert response.status_code == 200
        data = response.json()

        # Required fields from documentation
        assert "languages" in data
        assert isinstance(data["languages"], dict)

        assert "admin_default" in data
        assert "popular" in data
        assert isinstance(data["popular"], list)


class TestMessageHistoryAPI:
    """Test message history retrieval"""

    def test_get_messages_response_structure(self, client, active_session):
        """
        Test GET /api/session/{sessionId}/messages returns
        correct message structure as documented
        """
        session_id = active_session

        # Send a message first
        client.post(
            f"/api/session/{session_id}/message",
            json={
                "text": "Test message",
                "source_lang": "en",
                "target_lang": "de",
                "client_type": "admin"
            }
        )

        # Get message history
        response = client.get(f"/api/session/{session_id}/messages")

        assert response.status_code == 200
        data = response.json()

        assert "messages" in data
        messages = data["messages"]
        assert len(messages) > 0

        # Verify message structure from documentation
        message = messages[0]
        assert "original_text" in message
        assert "translated_text" in message  # ← Public API key
        assert "timestamp" in message

        # May have audio fields
        if "audio_base64" in message or "audio_url" in message:
            assert True  # Audio fields are optional


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
