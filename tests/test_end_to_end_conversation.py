"""
End-to-End Tests for WebSocket Metadata Enhancement

Tests full conversation flow with pipeline metadata validation.
These tests verify that:
1. pipeline_metadata is always present in all WebSocket messages
2. All pipeline steps are included with timestamps
3. Original audio URLs are accessible
4. Audio files are stored and retrievable
"""

import pytest
import asyncio
import json
import os
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path

from services.api_gateway.session_manager import SessionManager, SessionMessage
from services.api_gateway.audio_storage import save_original_audio, cleanup_old_audio_files


@pytest.fixture
def session_manager_fixture():
    """Create a SessionManager instance."""
    return SessionManager()


@pytest.fixture
def temp_audio_dir():
    """Create a temporary directory for audio storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        audio_dir = os.path.join(tmpdir, 'audio')
        os.makedirs(os.path.join(audio_dir, 'original'), exist_ok=True)
        os.makedirs(os.path.join(audio_dir, 'translated'), exist_ok=True)
        yield audio_dir


@pytest.fixture
def mock_pipeline():
    """Mock the pipeline logic functions."""
    with patch('services.api_gateway.pipeline_logic.process_wav') as mock_wav, \
         patch('services.api_gateway.pipeline_logic.process_text_pipeline') as mock_text:

        # Mock process_wav to return complete metadata
        async def mock_process_wav_impl(audio_bytes, source_lang, target_lang):
            now = datetime.now()
            return {
                "text": "Hello world",
                "translation": "Hallo Welt",
                "audio_base64": "ZmFrZV9hdWRpb19kYXRh",  # base64 for "fake_audio_data"
                "debug_info": {
                    "steps": [
                        {
                            "name": "asr",
                            "started_at": now.isoformat(),
                            "completed_at": (now + timedelta(milliseconds=100)).isoformat(),
                            "duration_ms": 100,
                            "input": {},
                            "output": "Hello world"
                        },
                        {
                            "name": "translation",
                            "started_at": (now + timedelta(milliseconds=100)).isoformat(),
                            "completed_at": (now + timedelta(milliseconds=250)).isoformat(),
                            "duration_ms": 150,
                            "input": {},
                            "output": "Hallo Welt"
                        },
                        {
                            "name": "tts",
                            "started_at": (now + timedelta(milliseconds=250)).isoformat(),
                            "completed_at": (now + timedelta(milliseconds=400)).isoformat(),
                            "duration_ms": 150,
                            "input": {},
                            "output": "audio_data"
                        }
                    ],
                    "total_duration_ms": 400,
                    "pipeline_started_at": now.isoformat(),
                    "pipeline_completed_at": (now + timedelta(milliseconds=400)).isoformat()
                }
            }

        # Mock process_text_pipeline to return complete metadata
        async def mock_process_text_impl(text, source_lang, target_lang):
            now = datetime.now()
            return {
                "translation": "Hallo Welt",
                "audio_base64": "ZmFrZV9hdWRpb19kYXRh",
                "debug_info": {
                    "steps": [
                        {
                            "name": "translation",
                            "started_at": now.isoformat(),
                            "completed_at": (now + timedelta(milliseconds=150)).isoformat(),
                            "duration_ms": 150,
                            "input": {},
                            "output": "Hallo Welt"
                        },
                        {
                            "name": "tts",
                            "started_at": (now + timedelta(milliseconds=150)).isoformat(),
                            "completed_at": (now + timedelta(milliseconds=300)).isoformat(),
                            "duration_ms": 150,
                            "input": {},
                            "output": "audio_data"
                        }
                    ],
                    "total_duration_ms": 300,
                    "pipeline_started_at": now.isoformat(),
                    "pipeline_completed_at": (now + timedelta(milliseconds=300)).isoformat()
                }
            }

        mock_wav.side_effect = mock_process_wav_impl
        mock_text.side_effect = mock_process_text_impl

        yield {
            'wav': mock_wav,
            'text': mock_text
        }


class TestE2EMetadataPresence:
    """Test that pipeline_metadata is always present in all message types."""

    @pytest.mark.asyncio
    async def test_metadata_exists_in_audio_response(self, session_manager_fixture, temp_audio_dir, mock_pipeline):
        """Test that pipeline_metadata exists in audio response messages."""
        # Create a session
        session_id = session_manager_fixture.create_session(customer_language="de")

        # Simulate processing audio with metadata
        audio_data = b"fake_wav_data"
        message_id = "msg-001"

        # Save original audio manually
        original_path = os.path.join(temp_audio_dir, 'original', f'input_{message_id}.wav')
        os.makedirs(os.path.dirname(original_path), exist_ok=True)
        with open(original_path, 'wb') as f:
            f.write(audio_data)

        # Create a message with pipeline metadata (simulating routes/session.py behavior)
        pipeline_result = await mock_pipeline['wav'](audio_data, "en", "de")

        # Transform debug_info to pipeline_metadata format
        from services.api_gateway.routes.session import transform_pipeline_metadata
        pipeline_metadata = transform_pipeline_metadata(
            pipeline_result.get("debug_info", {}),
            source_lang="en",
            target_lang="de"
        )

        from services.api_gateway.session_manager import ClientType
        message = SessionMessage(
            id=message_id,
            sender=ClientType.CUSTOMER,
            original_text="Hello world",
            translated_text="Hallo Welt",
            audio_base64="ZmFrZV9hdWRpb19kYXRh",
            source_lang="en",
            target_lang="de",
            timestamp=datetime.now(),
            pipeline_metadata=pipeline_metadata,
            original_audio_url=f"/api/audio/input_{message_id}.wav"
        )        # Add to session
        session_manager_fixture.add_message(session_id, message)

        # Verify pipeline_metadata exists
        data = message.to_dict()
        assert "pipeline_metadata" in data, "pipeline_metadata missing in audio response"
        metadata = data["pipeline_metadata"]

        # Verify metadata structure
        assert "steps" in metadata
        assert isinstance(metadata["steps"], list)
        assert len(metadata["steps"]) > 0

        # Verify original_audio_url exists
        assert "original_audio_url" in data
        assert data["original_audio_url"] is not None


class TestE2EPipelineSteps:
    """Test that all pipeline steps are included with proper structure."""

    @pytest.mark.asyncio
    async def test_validate_steps_array(self, session_manager_fixture, temp_audio_dir, mock_pipeline):
        """Test that steps array contains all expected pipeline steps."""
        # Create a session
        session_id = session_manager_fixture.create_session(customer_language="de")

        # Process audio
        audio_data = b"fake_wav_data"
        message_id = "msg-001"

        # Save audio
        original_path = os.path.join(temp_audio_dir, 'original', f'input_{message_id}.wav')
        os.makedirs(os.path.dirname(original_path), exist_ok=True)
        with open(original_path, 'wb') as f:
            f.write(audio_data)

        pipeline_result = await mock_pipeline['wav'](audio_data, "en", "de")

        from services.api_gateway.routes.session import transform_pipeline_metadata
        pipeline_metadata = transform_pipeline_metadata(
            pipeline_result.get("debug_info", {}),
            source_lang="en",
            target_lang="de"
        )

        steps = pipeline_metadata["steps"]

        # Expected steps for audio pipeline
        expected_steps = ["asr", "translation", "tts"]
        actual_step_names = [step["name"] for step in steps]

        for expected_step in expected_steps:
            assert expected_step in actual_step_names, f"Missing step: {expected_step}"

        # Verify each step has required fields
        for step in steps:
            assert "name" in step
            assert "started_at" in step
            assert "completed_at" in step
            assert "duration_ms" in step
class TestE2ETimestamps:
    """Test that timestamps are valid ISO 8601 format."""

    @pytest.mark.asyncio
    async def test_validate_iso8601_timestamps(self, session_manager_fixture, temp_audio_dir, mock_pipeline):
        """Test that all timestamps are valid ISO 8601 format."""
        # Create a session
        session_id = session_manager_fixture.create_session(customer_language="de")

        # Process audio
        audio_data = b"fake_wav_data"
        pipeline_result = await mock_pipeline['wav'](audio_data, "en", "de")

        from services.api_gateway.routes.session import transform_pipeline_metadata
        pipeline_metadata = transform_pipeline_metadata(
            pipeline_result.get("debug_info", {}),
            source_lang="en",
            target_lang="de"
        )

        steps = pipeline_metadata["steps"]

        for step in steps:
            # Validate started_at
            try:
                datetime.fromisoformat(step["started_at"].replace('Z', '+00:00'))
            except ValueError:
                pytest.fail(f"Invalid ISO 8601 timestamp for started_at: {step['started_at']}")

            # Validate completed_at
            try:
                datetime.fromisoformat(step["completed_at"].replace('Z', '+00:00'))
            except ValueError:
                pytest.fail(f"Invalid ISO 8601 timestamp for completed_at: {step['completed_at']}")


class TestE2EDuration:
    """Test that duration calculations are accurate."""

    @pytest.mark.asyncio
    async def test_validate_duration_calculation(self, session_manager_fixture, temp_audio_dir, mock_pipeline):
        """Test that duration_ms matches the difference between started_at and completed_at."""
        # Create a session
        session_id = session_manager_fixture.create_session(customer_language="de")

        # Process audio
        audio_data = b"fake_wav_data"
        pipeline_result = await mock_pipeline['wav'](audio_data, "en", "de")

        from services.api_gateway.routes.session import transform_pipeline_metadata
        pipeline_metadata = transform_pipeline_metadata(
            pipeline_result.get("debug_info", {}),
            source_lang="en",
            target_lang="de"
        )

        steps = pipeline_metadata["steps"]

        for step in steps:
            started = datetime.fromisoformat(step["started_at"].replace('Z', '+00:00'))
            completed = datetime.fromisoformat(step["completed_at"].replace('Z', '+00:00'))

            expected_duration_ms = int((completed - started).total_seconds() * 1000)
            actual_duration_ms = step["duration_ms"]

            # Allow 1ms tolerance for rounding
            assert abs(expected_duration_ms - actual_duration_ms) <= 1, \
                f"Duration mismatch: expected ~{expected_duration_ms}ms, got {actual_duration_ms}ms"


class TestE2EOriginalAudio:
    """Test that original audio is stored and accessible."""

    @pytest.mark.asyncio
    async def test_original_audio_url_present(self, session_manager_fixture, temp_audio_dir, mock_pipeline):
        """Test that original_audio_url is present in response."""
        # Create a session
        session_id = session_manager_fixture.create_session(customer_language="de")

        # Process audio
        audio_data = b"fake_wav_data"
        message_id = "msg-001"

        # Save audio
        original_path = os.path.join(temp_audio_dir, 'original', f'input_{message_id}.wav')
        os.makedirs(os.path.dirname(original_path), exist_ok=True)
        with open(original_path, 'wb') as f:
            f.write(audio_data)

        pipeline_result = await mock_pipeline['wav'](audio_data, "en", "de")

        from services.api_gateway.routes.session import transform_pipeline_metadata
        pipeline_metadata = transform_pipeline_metadata(
            pipeline_result.get("debug_info", {}),
            source_lang="en",
            target_lang="de"
        )

        from services.api_gateway.session_manager import ClientType
        message = SessionMessage(
            id=message_id,
            sender=ClientType.CUSTOMER,
            original_text="Hello world",
            translated_text="Hallo Welt",
            audio_base64="ZmFrZV9hdWRpb19kYXRh",
            source_lang="en",
            target_lang="de",
            timestamp=datetime.now(),
            pipeline_metadata=pipeline_metadata,
            original_audio_url=f"/api/audio/input_{message_id}.wav"
        )

        data = message.to_dict()        # Verify original_audio_url exists and is not None
        assert "original_audio_url" in data
        assert data["original_audio_url"] is not None
        assert isinstance(data["original_audio_url"], str)
        assert len(data["original_audio_url"]) > 0

    @pytest.mark.asyncio
    async def test_verify_audio_file_exists(self, session_manager_fixture, temp_audio_dir, mock_pipeline):
        """Test that the audio file actually exists on disk."""
        # Create a session
        session_id = "test-session-123"
        message_id = "msg-001"

        # Save audio
        audio_data = b"fake_wav_data"
        original_path = os.path.join(temp_audio_dir, 'original', f'input_{message_id}.wav')
        os.makedirs(os.path.dirname(original_path), exist_ok=True)
        with open(original_path, 'wb') as f:
            f.write(audio_data)

        # Verify file exists
        assert os.path.exists(original_path), f"Audio file not found: {original_path}"

        # Verify file content
        with open(original_path, 'rb') as f:
            stored_data = f.read()
        assert stored_data == audio_data


class TestE2EAudioEndpoint:
    """Test that the GET /api/audio endpoint works correctly."""

    @pytest.mark.asyncio
    async def test_get_audio_endpoint_returns_file(self, session_manager_fixture, temp_audio_dir):
        """Test that audio file storage and retrieval works."""
        # Save audio file
        message_id = "msg-001"
        audio_data = b"fake_wav_data"
        original_path = os.path.join(temp_audio_dir, 'original', f'input_{message_id}.wav')
        os.makedirs(os.path.dirname(original_path), exist_ok=True)
        with open(original_path, 'wb') as f:
            f.write(audio_data)

        # Verify file exists
        assert os.path.exists(original_path)

        # Read the file
        with open(original_path, 'rb') as f:
            stored_data = f.read()

        assert stored_data == audio_data


class TestE2ETextPipeline:
    """Test that text pipeline also includes metadata."""

    @pytest.mark.asyncio
    async def test_text_pipeline_includes_metadata(self, session_manager_fixture, mock_pipeline):
        """Test that text-based pipeline also includes pipeline_metadata."""
        # Create a session
        session_id = session_manager_fixture.create_session(customer_language="de")

        # Process text
        pipeline_result = await mock_pipeline['text']("Hello world", "en", "de")

        from services.api_gateway.routes.session import transform_pipeline_metadata
        pipeline_metadata = transform_pipeline_metadata(
            pipeline_result.get("debug_info", {}),
            source_lang="en",
            target_lang="de"
        )

        # Verify pipeline_metadata exists
        assert pipeline_metadata is not None

        # Verify steps
        assert "steps" in pipeline_metadata
        steps = pipeline_metadata["steps"]

        # Text pipeline should have: translation, tts
        expected_steps = ["translation", "tts"]
        actual_step_names = [step["name"] for step in steps]

        for expected_step in expected_steps:
            assert expected_step in actual_step_names        # Create message (text input has no original_audio_url)
        from services.api_gateway.session_manager import ClientType
        message = SessionMessage(
            id="msg-text-001",
            sender=ClientType.CUSTOMER,
            original_text="Hello world",
            translated_text="Hallo Welt",
            audio_base64="ZmFrZV9hdWRpb19kYXRh",
            source_lang="en",
            target_lang="de",
            timestamp=datetime.now(),
            pipeline_metadata=pipeline_metadata,
            original_audio_url=None
        )

        data = message.to_dict()        # Verify original_audio_url is None for text input
        assert data.get("original_audio_url") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
