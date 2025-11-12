"""
Integration Tests für Audio Recording Feature - ECHTE TESTS

Diese Tests verwenden FastAPI TestClient und testen die ECHTE Integration:
- /session/{session_id}/message Endpoint (multipart/form-data)
- ASR, Translation, TTS Service-Mocks
- Session-Manager Integration
- WebSocket-Broadcast (gemockt)

Run with: pytest tests/test_audio_upload_integration.py -v
"""

import io
import json
import pytest
import wave
import struct
import math
import asyncio
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
from datetime import datetime

from services.api_gateway.app import app
from services.api_gateway.session_manager import (
    SessionManager, SessionStatus, ClientType, SessionMessage, session_manager
)


# Configure pytest-asyncio
pytestmark = pytest.mark.asyncio


def create_test_wav(duration_seconds=2, sample_rate=16000):
    """Create a valid WAV file (16kHz, Mono, 16-bit PCM)"""
    buffer = io.BytesIO()

    with wave.open(buffer, 'wb') as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)

        # Generate sine wave (440 Hz tone)
        num_samples = duration_seconds * sample_rate
        for i in range(num_samples):
            sample = int(16384 * math.sin(2 * math.pi * 440 * i / sample_rate))
            wav_file.writeframes(struct.pack('<h', sample))

    buffer.seek(0)
    return buffer.read()


@pytest.fixture
def client():
    """FastAPI TestClient"""
    return TestClient(app)


@pytest.fixture
def test_session():
    """Create a test session"""
    from services.api_gateway.session_manager import Session

    # Use hash for predictable ID
    session_id = "TEST-" + str(abs(hash("test")))[:6]

    # Create session manually - Session is already a dataclass
    session = Session(
        id=session_id,
        customer_language="de",
        admin_language="en",
        status=SessionStatus.ACTIVE,
        admin_connected=True,
        customer_connected=True
    )

    # Add to session manager's dict
    session_manager.sessions[session_id] = session

    yield session

    # Cleanup
    if session_id in session_manager.sessions:
        del session_manager.sessions[session_id]


@pytest.fixture
def mock_pipeline_services():
    """Mock ASR, Translation, and TTS services"""

    # Mock process_wav (complete audio pipeline)
    async def mock_process_wav(audio_bytes, source_lang, target_lang, validate_audio=True, **kwargs):
        now = datetime.now()
        return {
            "original_text": "Hallo, das ist ein Test.",
            "translated_text": "Hello, this is a test.",
            "audio_base64": "UklGRiQAAABXQVZFZm10IBAAAAABAAEA",  # Minimal WAV header
            "debug_info": {
                "pipeline_started_at": now.isoformat(),
                "pipeline_completed_at": now.isoformat(),
                "total_duration_ms": 150,
                "steps": [
                    {
                        "name": "asr",
                        "started_at": now.isoformat(),
                        "completed_at": now.isoformat(),
                        "duration_ms": 50,
                        "output": "Hallo, das ist ein Test.",
                    },
                    {
                        "name": "translation",
                        "started_at": now.isoformat(),
                        "completed_at": now.isoformat(),
                        "duration_ms": 20,
                        "output": "Hello, this is a test.",
                    },
                    {
                        "name": "tts",
                        "started_at": now.isoformat(),
                        "completed_at": now.isoformat(),
                        "duration_ms": 80,
                    },
                ],
            },
        }

    with patch('services.api_gateway.routes.session.process_wav', new=mock_process_wav):
        yield
class TestAudioUploadIntegration:
    """Integration tests for audio upload endpoint"""

    def test_audio_upload_success(self, client, test_session, mock_pipeline_services):
        """
        Test successful audio upload with complete pipeline

        Scenario:
        - Upload valid WAV file
        - Backend processes: ASR → Translation → TTS
        - Return complete MessageResponse
        """
        wav_audio = create_test_wav(duration_seconds=2)

        files = {
            'file': ('audio.wav', io.BytesIO(wav_audio), 'audio/wav')
        }
        data = {
            'source_lang': test_session.customer_language,
            'target_lang': test_session.admin_language,
            'client_type': 'customer'
        }

        response = client.post(
            f'/api/session/{test_session.id}/message',
            files=files,
            data=data
        )

        # Assert successful response
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

        response_data = response.json()
        assert response_data['status'] == 'success'
        assert response_data['original_text'] == "Hallo, das ist ein Test."
        assert response_data['translated_text'] == "Hello, this is a test."
        assert 'audio_base64' in response_data
        assert 'message_id' in response_data

        # Verify pipeline metadata
        assert 'pipeline_metadata' in response_data
        metadata = response_data['pipeline_metadata']
        assert metadata['input']['type'] == 'audio'
        assert metadata['input']['source_lang'] == 'de'
        assert len(metadata['steps']) >= 2  # At least ASR and Translation

    def test_audio_upload_missing_file(self, client, test_session):
        """Test error handling when audio file is missing"""
        data = {
            'source_lang': 'de',
            'target_lang': 'en',
            'client_type': 'customer'
        }

        response = client.post(
            f'/api/session/{test_session.id}/message',
            data=data
        )

        assert response.status_code == 400
        response_data = response.json()
        assert 'detail' in response_data
        # FastAPI returns error in 'detail' field

    def test_audio_upload_invalid_session(self, client, mock_pipeline_services):
        """Test error handling for invalid session ID"""
        wav_audio = create_test_wav(duration_seconds=2)

        files = {
            'file': ('audio.wav', io.BytesIO(wav_audio), 'audio/wav')
        }
        data = {
            'source_lang': 'de',
            'target_lang': 'en',
            'client_type': 'customer'
        }

        response = client.post(
            '/api/session/invalid-session-id/message',
            files=files,
            data=data
        )

        assert response.status_code == 404
        response_data = response.json()
        assert 'detail' in response_data

    def test_audio_upload_missing_required_fields(self, client, test_session):
        """Test error handling when required fields are missing"""
        wav_audio = create_test_wav(duration_seconds=2)

        files = {
            'file': ('audio.wav', io.BytesIO(wav_audio), 'audio/wav')
        }
        # Missing source_lang, target_lang, client_type
        data = {}

        response = client.post(
            f'/api/session/{test_session.id}/message',
            files=files,
            data=data
        )

        assert response.status_code == 400
        response_data = response.json()
        assert 'detail' in response_data

    def test_audio_upload_invalid_client_type(self, client, test_session, mock_pipeline_services):
        """Test error handling for invalid client_type"""
        wav_audio = create_test_wav(duration_seconds=2)

        files = {
            'file': ('audio.wav', io.BytesIO(wav_audio), 'audio/wav')
        }
        data = {
            'source_lang': 'de',
            'target_lang': 'en',
            'client_type': 'invalid'  # Should be 'admin' or 'customer'
        }

        response = client.post(
            f'/api/session/{test_session.id}/message',
            files=files,
            data=data
        )

        # Should return 400 or 422 (validation error)
        assert response.status_code in [400, 422]

    def test_audio_upload_wav_format_validation(self, client, test_session, mock_pipeline_services):
        """Test that various WAV formats are accepted"""
        # Test different WAV formats
        test_cases = [
            (16000, "16kHz WAV"),
            (8000, "8kHz WAV"),
            (22050, "22kHz WAV"),
            (44100, "44.1kHz WAV"),
            (48000, "48kHz WAV"),
        ]

        for sample_rate, description in test_cases:
            wav_audio = create_test_wav(duration_seconds=1, sample_rate=sample_rate)

            files = {
                'file': (f'audio_{sample_rate}.wav', io.BytesIO(wav_audio), 'audio/wav')
            }
            data = {
                'source_lang': 'de',
                'target_lang': 'en',
                'client_type': 'customer'
            }

            response = client.post(
                f'/api/session/{test_session.id}/message',
                files=files,
                data=data
            )

            assert response.status_code == 200, f"{description} should be accepted, got {response.status_code}"

    def test_audio_upload_session_inactive(self, client, test_session, mock_pipeline_services):
        """Test error handling when session is not active"""
        # End the session to make it inactive
        from services.api_gateway.session_manager import session_manager
        session_manager.end_session(test_session.id)

        wav_audio = create_test_wav(duration_seconds=2)

        files = {
            'file': ('audio.wav', io.BytesIO(wav_audio), 'audio/wav')
        }
        data = {
            'source_lang': 'de',
            'target_lang': 'en',
            'client_type': 'customer'
        }

        response = client.post(
            f'/api/session/{test_session.id}/message',
            files=files,
            data=data
        )

        assert response.status_code == 400
        response_data = response.json()
        assert 'detail' in response_data

        # Recreate session for cleanup
        session_manager.create_session(
            session_id=test_session.id,
            source_lang=test_session.customer_language,
            target_lang=test_session.admin_language
        )

    def test_audio_upload_pipeline_error_handling(self, client, test_session):
        """Test error handling when pipeline fails"""

        # Mock process_wav to raise an error
        async def mock_process_wav_error(audio_bytes, source_lang, target_lang):
            raise Exception("ASR service unavailable")

        with patch('services.api_gateway.routes.session.process_wav', new=mock_process_wav_error):
            wav_audio = create_test_wav(duration_seconds=2)

            files = {
                'file': ('audio.wav', io.BytesIO(wav_audio), 'audio/wav')
            }
            data = {
                'source_lang': 'de',
                'target_lang': 'en',
                'client_type': 'customer'
            }

            response = client.post(
                f'/api/session/{test_session.id}/message',
                files=files,
                data=data
            )

            # Should return 500 or 503 (service error)
            assert response.status_code in [500, 503]
            response_data = response.json()
            assert 'detail' in response_data


class TestAudioUploadCrossBrowserFormats:
    """Test audio upload with different browser formats (simulated)"""

    def test_chrome_webm_converted_to_wav(self, client, test_session, mock_pipeline_services):
        """
        Test Chrome WebM/Opus → WAV conversion result

        In reality, the frontend converts WebM to WAV.
        This test validates that the backend accepts the converted WAV.
        """
        # Simulated: Chrome records WebM/Opus at 48kHz Stereo
        # Frontend converts to 16kHz Mono WAV
        wav_audio = create_test_wav(duration_seconds=2, sample_rate=16000)

        files = {
            'file': ('chrome_audio.wav', io.BytesIO(wav_audio), 'audio/wav')
        }
        data = {
            'source_lang': 'de',
            'target_lang': 'en',
            'client_type': 'customer'
        }

        response = client.post(
            f'/api/session/{test_session.id}/message',
            files=files,
            data=data
        )

        assert response.status_code == 200
        response_data = response.json()
        assert response_data['status'] == 'success'

    def test_firefox_ogg_converted_to_wav(self, client, test_session, mock_pipeline_services):
        """Test Firefox OGG/Opus → WAV conversion result"""
        wav_audio = create_test_wav(duration_seconds=2, sample_rate=16000)

        files = {
            'file': ('firefox_audio.wav', io.BytesIO(wav_audio), 'audio/wav')
        }
        data = {
            'source_lang': 'de',
            'target_lang': 'en',
            'client_type': 'customer'
        }

        response = client.post(
            f'/api/session/{test_session.id}/message',
            files=files,
            data=data
        )

        assert response.status_code == 200

    def test_safari_mp4_converted_to_wav(self, client, test_session, mock_pipeline_services):
        """Test Safari MP4/AAC → WAV conversion result"""
        wav_audio = create_test_wav(duration_seconds=2, sample_rate=16000)

        files = {
            'file': ('safari_audio.wav', io.BytesIO(wav_audio), 'audio/wav')
        }
        data = {
            'source_lang': 'de',
            'target_lang': 'en',
            'client_type': 'customer'
        }

        response = client.post(
            f'/api/session/{test_session.id}/message',
            files=files,
            data=data
        )

        assert response.status_code == 200


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
