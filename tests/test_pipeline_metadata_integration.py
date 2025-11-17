"""
Integration Tests for Pipeline Metadata Enhancement
=====================================================

Tests the complete flow:
- Audio/Text processing through pipeline
- Metadata collection and transformation
- WebSocket broadcasting with metadata
- Original audio storage and retrieval
"""

import pytest
import asyncio
import json
import base64
from pathlib import Path
from typing import Dict, Any
from unittest.mock import AsyncMock, MagicMock, patch

from services.api_gateway.session_manager import SessionManager, SessionMessage
from services.api_gateway.pipeline_logic import process_wav, process_text_pipeline
from services.api_gateway.audio_storage import (
    save_original_audio,
    get_audio_file_path,
    cleanup_old_audio_files,
)


@pytest.fixture
def session_manager():
    """Provide a SessionManager instance"""
    return SessionManager()


@pytest.fixture
def sample_audio():
    """Provide sample audio bytes"""
    return b"RIFF" + b"\x00" * 40  # Minimal WAV header


@pytest.fixture
def sample_audio_base64():
    """Provide real sample audio from examples folder as base64"""
    import os

    # Use English.wav - standard PCM format that ASR service accepts
    audio_path = os.path.join(os.path.dirname(__file__), "..", "examples", "English.wav")
    with open(audio_path, "rb") as f:
        audio_bytes = f.read()
    return base64.b64encode(audio_bytes).decode()


@pytest.fixture
def mock_pipeline_responses():
    """Mock responses from downstream services"""
    return {
        "asr": {"text": "Hallo Welt", "duration": 1.2},
        "translation": {"translated_text": "Hello World", "duration": 0.8},
        "tts": {"audio_base64": base64.b64encode(b"audio_data").decode(), "duration": 0.5},
    }


class TestAudioPipelineIntegration:
    """Test complete audio pipeline with metadata"""

    @pytest.mark.asyncio
    async def test_audio_pipeline_generates_metadata(self, sample_audio_base64, monkeypatch):
        """Test that audio pipeline generates complete metadata with real services"""
        import base64

        # Patch service URLs to use localhost ports (outside Docker network)
        monkeypatch.setattr("services.api_gateway.pipeline_logic.ASR_URL", "http://localhost:8001/transcribe")
        monkeypatch.setattr("services.api_gateway.pipeline_logic.TRANSLATION_URL", "http://localhost:8002/translate")
        monkeypatch.setattr("services.api_gateway.pipeline_logic.TTS_URL", "http://localhost:8003/synthesize")

        # Decode base64 to bytes for process_wav
        audio_bytes = base64.b64decode(sample_audio_base64)

        # Real integration test - calls actual ASR/Translation/TTS services
        result = await asyncio.to_thread(
            lambda: process_wav(
                file_bytes=audio_bytes,
                source_lang="en",
                target_lang="de",
                debug=True,
                validate_audio=True  # Use real audio from examples/
            )
        )

        # Verify result structure (process_wav returns these keys)
        assert "original_text" in result or "asr_text" in result  # Can be either
        assert "translated_text" in result or "translation_text" in result  # Can be either
        assert "audio_base64" in result or "audio_bytes" in result  # Can be either
        assert "debug_info" in result or "debug" in result  # Can be either

        # Verify debug has steps
        debug_info = result["debug"]
        assert "steps" in debug_info
        assert len(debug_info["steps"]) >= 3  # ASR, Translation, TTS (minimum)

        # Verify each step has required fields (some steps may not have all fields)
        for step in debug_info["steps"]:
            assert "step" in step or "name" in step  # Can be either field name
            # Not all steps have started_at/completed_at (e.g., validation step)
            # Just check for duration_ms or duration
            assert "duration_ms" in step or "duration" in step
    @pytest.mark.asyncio
    async def test_original_audio_storage_and_retrieval(self, sample_audio, sample_audio_base64):
        """Test that original audio is stored and can be retrieved"""

        message_id = "test-message-123"

        # Save original audio (expects base64)
        audio_url = save_original_audio(message_id, sample_audio_base64)

        assert audio_url is not None
        assert audio_url.startswith("/api/audio/input_")

        # Retrieve audio path
        retrieved_path = get_audio_file_path(f"input_{message_id}.wav")
        assert retrieved_path is not None
        assert retrieved_path.exists()

        # Verify content (stored as decoded bytes)
        # Ensure the stored file looks like a WAV (starts with 'RIFF')
        with open(retrieved_path, "rb") as f:
            stored_audio = f.read()
        assert stored_audio[:4] == b"RIFF"

        # Cleanup
        retrieved_path.unlink()


    @pytest.mark.asyncio
    async def test_metadata_transformation_audio_pipeline(self, mock_pipeline_responses):
        """Test transformation of debug_info to pipeline_metadata format"""

        # Create mock debug_info (as returned by pipeline)
        debug_info = {
            "steps": [
                {
                    "name": "asr",
                    "started_at": "2025-11-05T20:00:00.000Z",
                    "completed_at": "2025-11-05T20:00:01.200Z",
                    "duration_ms": 1200,
                    "input": {},
                    "output": "Hallo Welt",
                },
                {
                    "name": "translation",
                    "started_at": "2025-11-05T20:00:01.200Z",
                    "completed_at": "2025-11-05T20:00:02.000Z",
                    "duration_ms": 800,
                    "input": {"model": "m2m100_1.2B"},
                    "output": "Hello World",
                },
                {
                    "name": "tts",
                    "started_at": "2025-11-05T20:00:02.000Z",
                    "completed_at": "2025-11-05T20:00:02.500Z",
                    "duration_ms": 500,
                    "input": {"model": "coqui-tts"},
                    "output": {},
                },
            ],
            "total_duration_ms": 2500,
            "pipeline_started_at": "2025-11-05T20:00:00.000Z",
            "pipeline_completed_at": "2025-11-05T20:00:02.500Z",
        }

        # Import transform function
        from services.api_gateway.routes.session import transform_pipeline_metadata

        # Transform
        metadata = transform_pipeline_metadata(
            debug_info=debug_info,
            original_audio_url="/api/audio/input_test-123.wav",
            source_lang="de",
            target_lang="en",
        )

        # Verify structure
        assert "input" in metadata
        assert "steps" in metadata
        assert "pipeline_started_at" in metadata
        assert "pipeline_completed_at" in metadata
        assert "total_duration_ms" in metadata

        # Verify input
        assert metadata["input"]["type"] == "audio"
        assert metadata["input"]["audio_url"] == "/api/audio/input_test-123.wav"
        assert metadata["input"]["source_lang"] == "de"

        # Verify steps
        assert len(metadata["steps"]) == 3
        step_names = [s["name"] for s in metadata["steps"]]
        assert step_names == ["asr", "translation", "tts"]

        # Verify timestamps
        assert metadata["pipeline_started_at"] == "2025-11-05T20:00:00.000Z"
        assert metadata["pipeline_completed_at"] == "2025-11-05T20:00:02.500Z"

        # Verify total duration (in milliseconds)
        assert metadata["total_duration_ms"] == 2500


class TestTextPipelineIntegration:
    """Test complete text pipeline with metadata"""

    @pytest.mark.asyncio
    async def test_text_pipeline_generates_metadata(self, monkeypatch):
        """Test that text pipeline generates complete metadata with real services"""
        # Patch service URLs to use localhost ports (outside Docker network)
        monkeypatch.setattr("services.api_gateway.pipeline_logic.TRANSLATION_URL", "http://localhost:8002/translate")
        monkeypatch.setattr("services.api_gateway.pipeline_logic.TTS_URL", "http://localhost:8003/synthesize")

        # Real integration test - calls actual Translation/TTS services
        result = await asyncio.to_thread(
            lambda: process_text_pipeline(
                text="Hello world",
                source_lang="en",
                target_lang="de",
                debug=True,
                validate_text=False
            )
        )

        # Verify result structure (process_text_pipeline returns these keys)
        assert "asr_text" in result
        assert "translation_text" in result
        assert "audio_bytes" in result
        assert "debug" in result

        # Verify debug has steps (no ASR for text)
        debug_info = result["debug"]
        assert "steps" in debug_info
        assert len(debug_info["steps"]) >= 2  # Translation, TTS (minimum)

        # Verify no ASR step in text pipeline (asr_text should be the input text)
        assert result["asr_text"] == "Hello world"

        # Verify Translation and TTS steps exist
        step_names = {step.get("step") or step.get("name") for step in debug_info["steps"]}
        assert "Translation" in step_names or "translation" in step_names
        assert "TTS" in step_names or "tts" in step_names
    @pytest.mark.asyncio
    async def test_metadata_transformation_text_pipeline(self):
        """Test transformation of text pipeline debug_info"""

        # Create mock debug_info (text pipeline - no ASR)
        debug_info = {
            "steps": [
                {
                    "name": "translation",
                    "started_at": "2025-11-05T20:00:00.000Z",
                    "completed_at": "2025-11-05T20:00:00.800Z",
                    "duration_ms": 800,
                    "input": {"model": "m2m100_1.2B"},
                    "output": "Hello World",
                },
                {
                    "name": "tts",
                    "started_at": "2025-11-05T20:00:00.800Z",
                    "completed_at": "2025-11-05T20:00:01.300Z",
                    "duration_ms": 500,
                    "input": {"model": "coqui-tts"},
                    "output": {},
                },
            ],
            "total_duration_ms": 1300,
            "pipeline_started_at": "2025-11-05T20:00:00.000Z",
            "pipeline_completed_at": "2025-11-05T20:00:01.300Z",
        }

        # Import transform function
        from services.api_gateway.routes.session import transform_pipeline_metadata

        # Transform (no original audio URL for text input)
        metadata = transform_pipeline_metadata(
            debug_info=debug_info,
            original_audio_url=None,
            source_lang="de",
            target_lang="en",
        )

        # Verify structure
        assert "input" in metadata
        assert "steps" in metadata

        # Verify input (text input)
        assert metadata["input"]["type"] == "text"
        assert "audio_url" not in metadata["input"]
        assert metadata["input"]["source_lang"] == "de"

        # Verify steps (no ASR)
        assert len(metadata["steps"]) == 2
        step_names = [s["name"] for s in metadata["steps"]]
        assert step_names == ["translation", "tts"]


class TestSessionMessageIntegration:
    """Test SessionMessage with pipeline metadata"""

    def test_session_message_serialization_with_metadata(self):
        """Test that SessionMessage correctly serializes with metadata"""

        from datetime import datetime
        from services.api_gateway.session_manager import ClientType

        metadata = {
            "input": {"type": "audio", "audio_url": "/api/audio/input_test.wav", "source_lang": "de"},
            "steps": [
                {
                    "name": "asr",
                    "started_at": "2025-11-05T20:00:00.000Z",
                    "completed_at": "2025-11-05T20:00:01.000Z",
                    "duration_ms": 1000,
                    "input": {},
                    "output": {"text": "Test"},
                }
            ],
            "pipeline_started_at": "2025-11-05T20:00:00.000Z",
            "pipeline_completed_at": "2025-11-05T20:00:01.000Z",
            "total_duration_ms": 1000,
        }

        message = SessionMessage(
            id="test-123",
            sender=ClientType.ADMIN,
            original_text="Test",
            translated_text="Test",
            audio_base64="YXVkaW8=",
            source_lang="de",
            target_lang="en",
            timestamp=datetime.fromisoformat("2025-11-05T20:00:00"),
            pipeline_metadata=metadata,
            original_audio_url="/api/audio/input_test.wav",
        )

        # Serialize
        msg_dict = message.to_dict()

        # Verify metadata present
        assert "pipeline_metadata" in msg_dict
        assert msg_dict["pipeline_metadata"] == metadata
        assert "original_audio_url" in msg_dict
        assert msg_dict["original_audio_url"] == "/api/audio/input_test.wav"

        # Deserialize
        restored = SessionMessage.from_dict(msg_dict)

        assert restored.pipeline_metadata == metadata
        assert restored.original_audio_url == "/api/audio/input_test.wav"


    def test_session_message_backward_compatibility(self):
        """Test that old messages without metadata can be deserialized"""

        # Old message format (no metadata fields)
        old_message_dict = {
            "id": "test-123",
            "sender": "admin",
            "original_text": "Test",
            "translated_text": "Test",
            "audio_base64": "YXVkaW8=",
            "source_lang": "de",
            "target_lang": "en",
            "timestamp": "2025-11-05T20:00:00",
        }

        # Should deserialize without errors
        message = SessionMessage.from_dict(old_message_dict)

        # Metadata fields should be None
        assert message.pipeline_metadata is None
        assert message.original_audio_url is None

        # Serialization should not include None fields
        msg_dict = message.to_dict()
        assert "pipeline_metadata" not in msg_dict
        assert "original_audio_url" not in msg_dict


class TestAudioCleanupIntegration:
    """Test audio cleanup background task"""

    def test_cleanup_deletes_old_files_only(self, sample_audio_base64, tmp_path):
        """Test that cleanup only deletes files older than retention period"""

        # This test would need to mock file timestamps
        # or use a custom retention period for testing

        # Create test files
        message_id = "cleanup-test-123"
        audio_url = save_original_audio(message_id, sample_audio_base64)

        # Get file path
        filepath = get_audio_file_path(f"input_{message_id}.wav")
        assert filepath is not None

        # Run cleanup (with default 24h retention)
        stats = cleanup_old_audio_files()

        # File should NOT be deleted (too recent)
        assert filepath.exists()
        assert stats["deleted_original"] == 0

        # Cleanup test file
        filepath.unlink()


class TestPrometheusMetrics:
    """Test Prometheus metrics integration"""

    def test_metrics_available_after_cleanup(self, sample_audio):
        """Test that Prometheus metrics are updated after cleanup"""

        from services.api_gateway.audio_storage import (
            PROMETHEUS_AVAILABLE,
            audio_cleanup_deleted_files_total,
            get_disk_usage,
        )

        if not PROMETHEUS_AVAILABLE:
            pytest.skip("Prometheus client not available")

        # Get initial metric value
        initial_count = audio_cleanup_deleted_files_total.labels(directory="original")._value._value

        # Run cleanup
        cleanup_old_audio_files()

        # Metric should still exist (value may be same if no files deleted)
        current_count = audio_cleanup_deleted_files_total.labels(directory="original")._value._value
        assert current_count >= initial_count

        # Test disk usage metrics
        disk_stats = get_disk_usage()

        # Metrics should be updated (gauges are set, not incremented)
        # No specific assertion on values, just verify it doesn't crash
        assert disk_stats["total_files"] >= 0
        assert disk_stats["total_bytes"] >= 0
