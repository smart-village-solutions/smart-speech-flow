"""
Integration Tests für Pipeline Metadata Enhancement
Testet Audio Storage, Pipeline Metadata Collection und WebSocket Broadcasting
"""

import pytest
import base64
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
from services.api_gateway.session_manager import SessionMessage, ClientType
from services.api_gateway.routes.session import transform_pipeline_metadata


class TestPipelineMetadataTransformation:
    """Test Pipeline Metadata Transformation"""

    def test_transform_audio_pipeline_metadata(self):
        """Test transformation of audio pipeline debug info to spec format"""

        debug_info = {
            "pipeline_started_at": "2025-11-05T20:00:55.000Z",
            "pipeline_completed_at": "2025-11-05T20:01:00.000Z",
            "total_duration_ms": 5000,
            "steps": [
                {
                    "name": "asr",
                    "input": {"lang": "de"},
                    "output": "Hallo Welt",
                    "started_at": "2025-11-05T20:00:55.000Z",
                    "completed_at": "2025-11-05T20:00:57.500Z",
                    "duration_ms": 2500
                },
                {
                    "name": "translation",
                    "input": {"text": "Hallo Welt", "model": "m2m100_1.2B"},
                    "output": "Hello World",
                    "started_at": "2025-11-05T20:00:57.500Z",
                    "completed_at": "2025-11-05T20:00:58.000Z",
                    "duration_ms": 500
                },
                {
                    "name": "tts",
                    "input": {"lang": "en", "text": "Hello World"},
                    "output": "audio/wav",
                    "started_at": "2025-11-05T20:00:59.200Z",
                    "completed_at": "2025-11-05T20:01:00.000Z",
                    "duration_ms": 800
                }
            ]
        }

        result = transform_pipeline_metadata(
            debug_info,
            source_lang="de",
            target_lang="en",
            original_audio_url="/api/audio/input_test-123.wav",
            message_id="test-123"
        )

        # Verify structure
        assert result is not None
        assert result["input"]["type"] == "audio"
        assert result["input"]["source_lang"] == "de"
        assert result["input"]["audio_url"] == "/api/audio/input_test-123.wav"
        assert result["total_duration_ms"] == 5000
        assert result["pipeline_started_at"] == "2025-11-05T20:00:55.000Z"
        assert result["pipeline_completed_at"] == "2025-11-05T20:01:00.000Z"

        # Verify steps
        assert len(result["steps"]) == 3

        # ASR step
        asr_step = result["steps"][0]
        assert asr_step["name"] == "asr"
        assert asr_step["output"]["text"] == "Hallo Welt"
        assert asr_step["duration_ms"] == 2500

        # Translation step
        translation_step = result["steps"][1]
        assert translation_step["name"] == "translation"
        assert translation_step["output"]["text"] == "Hello World"
        assert translation_step["output"]["model"] == "m2m100_1.2B"

        # TTS step
        tts_step = result["steps"][2]
        assert tts_step["name"] == "tts"
        assert tts_step["output"]["audio_url"] == "/api/audio/test-123.wav"
        assert tts_step["output"]["format"] == "wav"

    def test_transform_text_pipeline_metadata(self):
        """Test transformation of text pipeline (no audio input)"""

        debug_info = {
            "pipeline_started_at": "2025-11-05T20:00:55.000Z",
            "pipeline_completed_at": "2025-11-05T20:00:58.000Z",
            "total_duration_ms": 3000,
            "steps": [
                {
                    "name": "translation",
                    "input": {"text": "Hello", "model": "m2m100_1.2B"},
                    "output": "Hallo",
                    "started_at": "2025-11-05T20:00:55.000Z",
                    "completed_at": "2025-11-05T20:00:56.000Z",
                    "duration_ms": 1000
                },
                {
                    "name": "tts",
                    "input": {"lang": "de", "text": "Hallo"},
                    "output": "audio/wav",
                    "started_at": "2025-11-05T20:00:56.000Z",
                    "completed_at": "2025-11-05T20:00:58.000Z",
                    "duration_ms": 2000
                }
            ]
        }

        result = transform_pipeline_metadata(
            debug_info,
            source_lang="en",
            target_lang="de",
            original_audio_url=None,  # Text pipeline
            message_id="text-123"
        )

        # Verify text input
        assert result["input"]["type"] == "text"
        assert result["input"]["source_lang"] == "en"
        assert "audio_url" not in result["input"]

        # Verify steps (no ASR)
        assert len(result["steps"]) == 2
        assert result["steps"][0]["name"] == "translation"
        assert result["steps"][1]["name"] == "tts"

    def test_transform_with_refinement(self):
        """Test pipeline with LLM refinement step"""

        debug_info = {
            "pipeline_started_at": "2025-11-05T20:00:55.000Z",
            "pipeline_completed_at": "2025-11-05T20:01:02.000Z",
            "total_duration_ms": 7000,
            "steps": [
                {
                    "name": "translation",
                    "input": {"text": "Test", "model": "m2m100_1.2B"},
                    "output": "Test translated",
                    "started_at": "2025-11-05T20:00:55.000Z",
                    "completed_at": "2025-11-05T20:00:56.000Z",
                    "duration_ms": 1000
                },
                {
                    "name": "llm_refinement",
                    "input": {"enabled": True, "changed": True},
                    "output": "Test refined",
                    "started_at": "2025-11-05T20:00:56.000Z",
                    "completed_at": "2025-11-05T20:00:58.000Z",
                    "duration_ms": 2000
                },
                {
                    "name": "tts",
                    "input": {"lang": "en", "text": "Test refined"},
                    "output": "audio/wav",
                    "started_at": "2025-11-05T20:00:58.000Z",
                    "completed_at": "2025-11-05T20:01:02.000Z",
                    "duration_ms": 4000
                }
            ]
        }

        result = transform_pipeline_metadata(
            debug_info,
            source_lang="de",
            target_lang="en",
            original_audio_url=None,
            message_id="refine-123"
        )

        # Verify refinement step is properly transformed
        refinement_step = result["steps"][1]
        assert refinement_step["name"] == "refinement"  # Normalized name
        assert refinement_step["output"]["text"] == "Test refined"
        assert refinement_step["output"]["changed"] == True
        assert refinement_step["duration_ms"] == 2000


class TestSessionMessageEnhancement:
    """Test SessionMessage with pipeline_metadata"""

    def test_session_message_with_metadata(self):
        """Test SessionMessage creation and serialization with metadata"""

        pipeline_metadata = {
            "input": {"type": "audio", "source_lang": "de"},
            "steps": [],
            "total_duration_ms": 5000,
            "pipeline_started_at": "2025-11-05T20:00:00.000Z",
            "pipeline_completed_at": "2025-11-05T20:00:05.000Z"
        }

        message = SessionMessage(
            id="msg-123",
            sender=ClientType.ADMIN,
            original_text="Hallo",
            translated_text="Hello",
            audio_base64="base64data",
            source_lang="de",
            target_lang="en",
            timestamp=datetime(2025, 11, 5, 20, 0, 0),
            pipeline_metadata=pipeline_metadata,
            original_audio_url="/api/audio/input_msg-123.wav"
        )

        # Test to_dict()
        data = message.to_dict()
        assert data["id"] == "msg-123"
        assert data["pipeline_metadata"] == pipeline_metadata
        assert data["original_audio_url"] == "/api/audio/input_msg-123.wav"

        # Test from_dict()
        restored = SessionMessage.from_dict(data)
        assert restored.id == "msg-123"
        assert restored.pipeline_metadata == pipeline_metadata
        assert restored.original_audio_url == "/api/audio/input_msg-123.wav"

    def test_session_message_without_metadata(self):
        """Test SessionMessage backward compatibility (no metadata)"""

        message = SessionMessage(
            id="msg-456",
            sender=ClientType.CUSTOMER,
            original_text="Hello",
            translated_text="Hallo",
            audio_base64=None,
            source_lang="en",
            target_lang="de",
            timestamp=datetime(2025, 11, 5, 20, 0, 0),
        )

        # Metadata fields should be None
        assert message.pipeline_metadata is None
        assert message.original_audio_url is None

        # to_dict() should not include None fields
        data = message.to_dict()
        assert "pipeline_metadata" not in data
        assert "original_audio_url" not in data


class TestAudioStorage:
    """Test Audio Storage Service"""

    def test_save_and_get_original_audio(self):
        """Test saving and retrieving original audio"""
        from services.api_gateway.audio_storage import save_original_audio, get_audio_file_path

        message_id = "test-audio-123"
        audio_data = b"fake audio data"
        audio_base64 = base64.b64encode(audio_data).decode()

        # Save
        url = save_original_audio(message_id, audio_base64)
        assert url == f"/api/audio/input_{message_id}.wav"

        # Get
        filepath = get_audio_file_path(f"input_{message_id}.wav")
        assert filepath is not None
        assert filepath.exists()

        # Verify content
        saved_data = filepath.read_bytes()
        assert saved_data == audio_data

        # Cleanup
        filepath.unlink()

    def test_cleanup_old_audio_files(self):
        """Test audio cleanup job"""
        from services.api_gateway.audio_storage import cleanup_old_audio_files, save_original_audio
        import time

        # Save test file
        message_id = "cleanup-test-123"
        audio_base64 = base64.b64encode(b"test data").decode()
        save_original_audio(message_id, audio_base64)

        # Cleanup (should not delete recent file)
        stats = cleanup_old_audio_files()
        assert stats["deleted_original"] == 0  # File is too recent

        # Cleanup test file
        from services.api_gateway.audio_storage import ORIGINAL_AUDIO_DIR
        filepath = ORIGINAL_AUDIO_DIR / f"input_{message_id}.wav"
        if filepath.exists():
            filepath.unlink()

    def test_get_disk_usage(self):
        """Test disk usage statistics"""
        from services.api_gateway.audio_storage import get_disk_usage

        stats = get_disk_usage()
        assert "total_bytes" in stats
        assert "original_bytes" in stats
        assert "translated_bytes" in stats
        assert "total_files" in stats
        assert stats["total_bytes"] == stats["original_bytes"] + stats["translated_bytes"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
