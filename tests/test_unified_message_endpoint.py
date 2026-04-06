# tests/test_unified_message_endpoint.py
"""
Unit-Tests für den einheitlichen Message-Endpunkt (ToDo 2.1)
Testet Content-Type-basierte Auto-Detection, Audio/Text-Pipeline und Unified Response-Format
"""

import pytest
import json
import base64
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch

# Session-Manager und Dependencies
from services.api_gateway.session_manager import SessionManager, ClientType, SessionStatus
from services.api_gateway.routes.session import (
    TextMessageRequest, MessageResponse, ErrorResponse
)


@pytest.fixture
def session_manager():
    """Session-Manager für Tests"""
    return SessionManager()


@pytest.fixture
async def active_session(session_manager):
    """Aktive Session für Tests"""
    session_id = await session_manager.create_admin_session()

    # Session auf ACTIVE setzen
    session = session_manager.get_session(session_id)
    session.status = SessionStatus.ACTIVE
    session.customer_language = "en"

    return session_id


@pytest.fixture
def mock_request_json():
    """Mock-Request für JSON-Payload"""
    request = Mock()
    request.headers = {"content-type": "application/json"}
    request.json = AsyncMock(return_value={
        "text": "Hello, how can I help you?",
        "source_lang": "en",
        "target_lang": "de",
        "client_type": "admin"
    })
    return request


@pytest.fixture
def mock_request_multipart():
    """Mock-Request für Multipart-Form-Data"""
    request = Mock()
    request.headers = {"content-type": "multipart/form-data; boundary=boundary"}

    # Mock UploadFile
    mock_file = Mock()
    mock_file.read = AsyncMock(return_value=b"fake_wav_data")

    form_data = {
        "file": mock_file,
        "source_lang": "de",
        "target_lang": "en",
        "client_type": "admin"
    }
    request.form = AsyncMock(return_value=form_data)
    return request


@pytest.fixture
def mock_audio_bytes():
    """Mock-Audio-Bytes für Tests"""
    return b"RIFF" + b"fake_wav_audio_data" + b"\x00" * 100


class TestPydanticModels:
    """Tests für Pydantic-Request/Response-Models"""

    def test_text_message_request_valid(self):
        """Test: Gültiges TextMessageRequest"""
        request = TextMessageRequest(
            text="Hello world",
            source_lang="en",
            target_lang="de",
            client_type=ClientType.ADMIN
        )

        assert request.text == "Hello world"
        assert request.source_lang == "en"
        assert request.target_lang == "de"
        assert request.client_type == ClientType.ADMIN

    def test_text_message_request_validation_errors(self):
        """Test: TextMessageRequest Validierung"""
        # Leerer Text
        with pytest.raises(ValueError):
            TextMessageRequest(
                text="",
                source_lang="en",
                target_lang="de",
                client_type=ClientType.ADMIN
            )

        # Text zu lang
        with pytest.raises(ValueError):
            TextMessageRequest(
                text="x" * 501,  # Über 500 Zeichen
                source_lang="en",
                target_lang="de",
                client_type=ClientType.ADMIN
            )

        # Whitespace-only Text
        with pytest.raises(ValueError):
            TextMessageRequest(
                text="   ",
                source_lang="en",
                target_lang="de",
                client_type=ClientType.ADMIN
            )

    def test_message_response_model(self):
        """Test: MessageResponse-Model"""
        response = MessageResponse(
            status="success",
            message_id="msg_123",
            session_id="session_456",
            original_text="Hello",
            translated_text="Hallo",
            audio_available=True,
            audio_url="/api/audio/msg_123.wav",
            processing_time_ms=1500,
            pipeline_type="text",
            source_lang="en",
            target_lang="de",
            timestamp="2025-09-28T14:30:00Z"
        )

        assert response.status == "success"
        assert response.audio_available is True
        assert response.processing_time_ms == 1500
        assert response.pipeline_type == "text"

    def test_error_response_model(self):
        """Test: ErrorResponse-Model"""
        error = ErrorResponse(
            error_code="SESSION_NOT_FOUND",
            error_message="Session not found",
            details={"session_id": "ABC123"},
            timestamp="2025-09-28T14:30:00Z"
        )

        assert error.status == "error"
        assert error.error_code == "SESSION_NOT_FOUND"
        assert error.details["session_id"] == "ABC123"


class TestContentTypeDetection:
    """Tests für Content-Type-basierte Auto-Detection"""

    @pytest.mark.asyncio
    async def test_json_content_type_detection(self, active_session, mock_request_json):
        """Test: JSON Content-Type wird erkannt und Text-Pipeline ausgeführt"""
        from services.api_gateway.routes.session import send_unified_message

        # Mock Text-Pipeline
        with patch('services.api_gateway.routes.session.process_text_input') as mock_text_pipeline:
            mock_response = MessageResponse(
                status="success",
                message_id="msg_123",
                session_id=active_session,
                original_text="Hello",
                translated_text="Hallo",
                audio_available=False,
                processing_time_ms=800,
                pipeline_type="text",
                source_lang="en",
                target_lang="de",
                timestamp=datetime.now().isoformat()
            )
            mock_text_pipeline.return_value = mock_response

            # Test ausführen
            result = await send_unified_message(active_session, mock_request_json)

            # Assertions
            assert result.pipeline_type == "text"
            mock_text_pipeline.assert_called_once()

    @pytest.mark.asyncio
    async def test_multipart_content_type_detection(self, active_session, mock_request_multipart):
        """Test: Multipart Content-Type wird erkannt und Audio-Pipeline ausgeführt"""
        from services.api_gateway.routes.session import send_unified_message

        # Mock Audio-Pipeline
        with patch('services.api_gateway.routes.session.process_audio_input') as mock_audio_pipeline:
            mock_response = MessageResponse(
                status="success",
                message_id="msg_456",
                session_id=active_session,
                original_text="Guten Tag",
                translated_text="Good day",
                audio_available=True,
                audio_url="/api/audio/msg_456.wav",
                processing_time_ms=2500,
                pipeline_type="audio",
                source_lang="de",
                target_lang="en",
                timestamp=datetime.now().isoformat()
            )
            mock_audio_pipeline.return_value = mock_response

            # Test ausführen
            result = await send_unified_message(active_session, mock_request_multipart)

            # Assertions
            assert result.pipeline_type == "audio"
            mock_audio_pipeline.assert_called_once()

    @pytest.mark.asyncio
    async def test_unsupported_content_type(self, active_session):
        """Test: Unsupported Content-Type führt zu Fehler"""
        from services.api_gateway.routes.session import send_unified_message
        from fastapi import HTTPException

        # Mock-Request mit unsupported Content-Type
        request = Mock()
        request.headers = {"content-type": "text/plain"}

        # Test ausführen
        with pytest.raises(HTTPException) as exc_info:
            await send_unified_message(active_session, request)

        # Assertions
        assert exc_info.value.status_code == 400
        assert "UNSUPPORTED_CONTENT_TYPE" in str(exc_info.value.detail)


class TestTextPipeline:
    """Tests für Text-Pipeline (JSON-Input)"""

    @pytest.mark.asyncio
    async def test_text_pipeline_success(self, active_session):
        """Test: Text-Pipeline erfolgreich"""
        from services.api_gateway.routes.session import process_text_input

        # Mock-Request
        request = Mock()
        request.json = AsyncMock(return_value={
            "text": "How are you?",
            "source_lang": "en",
            "target_lang": "de",
            "client_type": "customer"
        })

        # Mock Translation/TTS Pipeline
        with patch('services.api_gateway.routes.session.process_text_pipeline') as mock_translation:
            mock_translation.return_value = {
                "error": False,
                "asr_text": "How are you?",
                "translation_text": "Wie geht es dir?",
                "audio_bytes": b"fake_tts_audio",
                "debug": {
                    "steps": [
                        {"step": "Text_Validation", "output": True, "error": None},
                        {"step": "Translation", "output": "Wie geht es dir?", "error": None},
                        {"step": "TTS", "output": "audio/wav", "error": None}
                    ],
                    "total_duration": 0.123
                }
            }

            # Test ausführen
            start_time = 0.0
            result = await process_text_input(active_session, request, start_time)

            # Assertions
            assert result.status == "success"
            assert result.original_text == "How are you?"
            assert result.translated_text == "Wie geht es dir?"
            assert result.pipeline_type == "text"
            assert result.audio_available is True
            assert result.source_lang == "en"
            assert result.target_lang == "de"

    @pytest.mark.asyncio
    async def test_text_pipeline_invalid_json(self, active_session):
        """Test: Ungültiges JSON führt zu Fehler"""
        from services.api_gateway.routes.session import process_text_input
        from fastapi import HTTPException

        # Mock-Request mit ungültigem JSON
        request = Mock()
        request.json = AsyncMock(side_effect=json.JSONDecodeError("Expecting value", "test", 0))

        # Test ausführen
        with pytest.raises(HTTPException) as exc_info:
            await process_text_input(active_session, request, 0.0)

        # Assertions
        assert exc_info.value.status_code == 400
        assert "INVALID_JSON" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_text_pipeline_unsupported_language(self, active_session):
        """Test: Nicht unterstützte Sprache führt zu Fehler"""
        from services.api_gateway.routes.session import process_text_input
        from fastapi import HTTPException

        # Mock-Request mit unsupported Language
        request = Mock()
        request.json = AsyncMock(return_value={
            "text": "Hello",
            "source_lang": "xyz",  # Nicht unterstützte Sprache
            "target_lang": "de",
            "client_type": "admin"
        })

        # Test ausführen
        with pytest.raises(HTTPException) as exc_info:
            await process_text_input(active_session, request, 0.0)

        # Assertions
        assert exc_info.value.status_code == 400
        assert "UNSUPPORTED_LANGUAGE" in str(exc_info.value.detail)


class TestAudioPipeline:
    """Tests für Audio-Pipeline (Multipart-Input)"""

    @pytest.mark.asyncio
    async def test_audio_pipeline_success(self, active_session, mock_audio_bytes):
        """Test: Audio-Pipeline erfolgreich"""
        from services.api_gateway.routes.session import process_audio_input

        # Mock-Request mit Form-Data
        request = Mock()
        mock_file = Mock()
        mock_file.read = AsyncMock(return_value=mock_audio_bytes)

        form_data = {
            "file": mock_file,
            "source_lang": "de",
            "target_lang": "en",
            "client_type": "admin"
        }
        request.form = AsyncMock(return_value=form_data)

        # Mock Audio-Pipeline
        with patch('services.api_gateway.routes.session.process_wav') as mock_process_wav:
            mock_process_wav.return_value = {
                "error": False,
                "asr_text": "Guten Tag",
                "translation_text": "Good day",
                "audio_bytes": b"fake_output_audio"
            }

            # Test ausführen
            start_time = 0.0
            result = await process_audio_input(active_session, request, start_time)

            # Assertions
            assert result.status == "success"
            assert result.original_text == "Guten Tag"
            assert result.translated_text == "Good day"
            assert result.pipeline_type == "audio"
            assert result.audio_available is True
            assert result.source_lang == "de"
            assert result.target_lang == "en"

    @pytest.mark.asyncio
    async def test_audio_pipeline_missing_fields(self, active_session):
        """Test: Fehlende Form-Fields führen zu Fehler"""
        from services.api_gateway.routes.session import process_audio_input
        from fastapi import HTTPException

        # Mock-Request mit unvollständigen Form-Data
        request = Mock()
        form_data = {
            "file": Mock(),
            "source_lang": "de"
            # target_lang und client_type fehlen
        }
        request.form = AsyncMock(return_value=form_data)

        # Test ausführen
        with pytest.raises(HTTPException) as exc_info:
            await process_audio_input(active_session, request, 0.0)

        # Assertions
        assert exc_info.value.status_code == 400
        assert "MISSING_FIELDS" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_audio_pipeline_invalid_file(self, active_session):
        """Test: Ungültige Audio-Datei führt zu Fehler"""
        from services.api_gateway.routes.session import process_audio_input
        from fastapi import HTTPException

        # Mock-Request mit ungültiger Datei
        request = Mock()
        form_data = {
            "file": "not_a_file_object",  # Kein File-Object
            "source_lang": "de",
            "target_lang": "en",
            "client_type": "admin"
        }
        request.form = AsyncMock(return_value=form_data)

        # Test ausführen
        with pytest.raises(HTTPException) as exc_info:
            await process_audio_input(active_session, request, 0.0)

        # Assertions
        assert exc_info.value.status_code == 400
        assert "INVALID_FILE" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_audio_pipeline_processing_error(self, active_session, mock_audio_bytes):
        """Test: Pipeline-Processing-Fehler"""
        from services.api_gateway.routes.session import process_audio_input
        from fastapi import HTTPException

        # Mock-Request
        request = Mock()
        mock_file = Mock()
        mock_file.read = AsyncMock(return_value=mock_audio_bytes)

        form_data = {
            "file": mock_file,
            "source_lang": "de",
            "target_lang": "en",
            "client_type": "admin"
        }
        request.form = AsyncMock(return_value=form_data)

        # Mock Pipeline mit Fehler
        with patch('services.api_gateway.routes.session.process_wav') as mock_process_wav:
            mock_process_wav.return_value = {
                "error": True,
                "error_msg": "ASR service unavailable"
            }

            # Test ausführen
            with pytest.raises(HTTPException) as exc_info:
                await process_audio_input(active_session, request, 0.0)

            # Assertions
            assert exc_info.value.status_code == 500
            assert "PIPELINE_ERROR" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_audio_pipeline_uses_processed_audio_bytes(self, active_session, mock_audio_bytes):
        """Test: Erfolgreich validierte/normalisierte Audio-Bytes werden weitergereicht."""
        from services.api_gateway.routes.session import process_audio_input

        request = Mock()
        mock_file = Mock()
        mock_file.read = AsyncMock(return_value=mock_audio_bytes)

        form_data = {
            "file": mock_file,
            "source_lang": "de",
            "target_lang": "en",
            "client_type": "admin"
        }
        request.form = AsyncMock(return_value=form_data)

        processed_audio = b"processed-audio"
        validation_result = Mock(is_valid=True, processed_audio=processed_audio)

        with patch(
            'services.api_gateway.routes.session._should_validate_upload_file',
            return_value=True,
        ), patch(
            'services.api_gateway.pipeline_logic.validate_audio_input',
            return_value=validation_result,
        ), patch('services.api_gateway.routes.session.process_wav') as mock_process_wav:
            mock_process_wav.return_value = {
                "error": False,
                "asr_text": "Guten Tag",
                "translation_text": "Good day",
                "audio_bytes": b"fake_output_audio"
            }

            await process_audio_input(active_session, request, 0.0)

            mock_process_wav.assert_called_once_with(
                processed_audio, "de", "en", validate_audio=False
            )


class TestSessionValidation:
    """Tests für Session-Validation und Error-Handling"""

    @pytest.mark.asyncio
    async def test_session_not_found(self, mock_request_json):
        """Test: Session nicht gefunden"""
        from services.api_gateway.routes.session import send_unified_message
        from fastapi import HTTPException

        # Test mit nicht-existierender Session
        with pytest.raises(HTTPException) as exc_info:
            await send_unified_message("NONEXISTENT_SESSION", mock_request_json)

        # Assertions
        assert exc_info.value.status_code == 404
        assert "SESSION_NOT_FOUND" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_session_not_active(self, session_manager, mock_request_json):
        """Test: Session nicht aktiv"""
        from services.api_gateway.routes.session import send_unified_message
        from fastapi import HTTPException

        # Session erstellen aber nicht aktivieren
        session_id = await session_manager.create_admin_session()
        session = session_manager.get_session(session_id)
        session.status = SessionStatus.TERMINATED

        # Test ausführen
        with pytest.raises(HTTPException) as exc_info:
            await send_unified_message(session_id, mock_request_json)

        # Assertions
        assert exc_info.value.status_code == 400
        assert "SESSION_NOT_ACTIVE" in str(exc_info.value.detail)


class TestSessionMessageCreation:
    """Tests für Session-Message-Erstellung"""

    @pytest.mark.asyncio
    async def test_create_session_message(self, active_session, mock_audio_bytes):
        """Test: Session-Message erstellen"""
        from services.api_gateway.routes.session import create_session_message

        # Message erstellen
        message = await create_session_message(
            session_id=active_session,
            client_type=ClientType.ADMIN,
            original_text="Hello",
            translated_text="Hallo",
            audio_bytes=mock_audio_bytes,
            source_lang="en",
            target_lang="de"
        )

        # Assertions
        assert message.id is not None
        assert message.sender == ClientType.ADMIN
        assert message.original_text == "Hello"
        assert message.translated_text == "Hallo"
        assert message.audio_base64 is not None
        assert message.source_lang == "en"
        assert message.target_lang == "de"

        # Message wurde zur Session hinzugefügt
        from services.api_gateway.session_manager import session_manager
        session = session_manager.get_session(active_session)
        assert len(session.messages) == 1
        assert session.messages[0].id == message.id

    @pytest.mark.asyncio
    async def test_create_session_message_fallback_only_for_legacy_signature(self, active_session):
        """Test: Legacy-Fallback greift nur bei alter Signatur, nicht bei internem TypeError."""
        from services.api_gateway.routes import session as session_routes

        async def legacy_create_session_message(
            session_id,
            client_type,
            original_text,
            translated_text,
            audio_bytes,
            source_lang,
            target_lang,
        ):
            return session_routes.SessionMessage(
                id="legacy-msg",
                sender=client_type,
                original_text=original_text,
                translated_text=translated_text,
                audio_base64=None,
                source_lang=source_lang,
                target_lang=target_lang,
                timestamp=datetime.now(),
            )

        with patch.object(
            session_routes,
            "create_session_message",
            legacy_create_session_message,
        ):
            message = await session_routes._create_session_message_with_fallback(
                session_id=active_session,
                client_type=ClientType.ADMIN,
                original_text="Hello",
                translated_text="Hallo",
                audio_bytes=None,
                source_lang="en",
                target_lang="de",
                manager=None,
                pipeline_metadata=None,
                original_audio_url=None,
                message_id="ignored",
            )

        assert message.id == "legacy-msg"

        async def raising_create_session_message(*args, **kwargs):
            raise TypeError("internal failure")

        with patch.object(
            session_routes,
            "create_session_message",
            raising_create_session_message,
        ):
            with pytest.raises(TypeError, match="internal failure"):
                await session_routes._create_session_message_with_fallback(
                    session_id=active_session,
                    client_type=ClientType.ADMIN,
                    original_text="Hello",
                    translated_text="Hallo",
                    audio_bytes=None,
                    source_lang="en",
                    target_lang="de",
                    manager=None,
                    pipeline_metadata=None,
                    original_audio_url=None,
                    message_id="ignored",
                )


class TestAudioEndpoint:
    """Tests für Audio-File-Endpunkt"""

    @pytest.mark.asyncio
    async def test_get_message_audio_success(self, active_session, mock_audio_bytes):
        """Test: Audio-Datei erfolgreich abrufen"""
        from services.api_gateway.routes.session import get_message_audio, create_session_message

        # Message mit Audio erstellen
        message = await create_session_message(
            session_id=active_session,
            client_type=ClientType.ADMIN,
            original_text="Test",
            translated_text="Test",
            audio_bytes=mock_audio_bytes,
            source_lang="en",
            target_lang="de"
        )

        # Audio abrufen
        response = await get_message_audio(message.id)

        # Assertions
        assert response.media_type == "audio/wav"
        assert response.body == mock_audio_bytes
        assert f"message_{message.id}.wav" in response.headers["Content-Disposition"]

    @pytest.mark.asyncio
    async def test_get_message_audio_not_found(self):
        """Test: Audio-Datei nicht gefunden"""
        from services.api_gateway.routes.session import get_message_audio
        from fastapi import HTTPException

        # Test mit nicht-existierender Message-ID
        with pytest.raises(HTTPException) as exc_info:
            await get_message_audio("NONEXISTENT_MESSAGE")

        # Assertions
        assert exc_info.value.status_code == 404
        assert "Audio file not found" in str(exc_info.value.detail)


class TestEndToEndIntegration:
    """End-to-End-Integration-Tests"""

    @pytest.mark.asyncio
    async def test_text_message_end_to_end(self, active_session):
        """Test: Komplette Text-Message von Request bis Response"""
        from services.api_gateway.routes.session import send_unified_message

        # Mock-Request
        request = Mock()
        request.headers = {"content-type": "application/json"}
        request.json = AsyncMock(return_value={
            "text": "How are you today?",
            "source_lang": "en",
            "target_lang": "de",
            "client_type": "customer"
        })

        # Mock Services
        with patch('services.api_gateway.routes.session.process_text_pipeline') as mock_translation:
            fake_audio = b"fake_tts_audio_bytes"
            mock_translation.return_value = {
                "error": False,
                "asr_text": "How are you today?",
                "translation_text": "Wie geht es dir heute?",
                "audio_bytes": fake_audio,
                "debug": {"steps": [], "total_duration": 0.222}
            }

            # Test ausführen
            result = await send_unified_message(active_session, request)

            # Assertions
            assert result.status == "success"
            assert result.session_id == active_session
            assert result.original_text == "How are you today?"
            assert result.translated_text == "Wie geht es dir heute?"
            assert result.pipeline_type == "text"
            assert result.audio_available is True
            assert result.processing_time_ms > 0

            # Message wurde gespeichert
            from services.api_gateway.session_manager import session_manager
            session = session_manager.get_session(active_session)
            assert len(session.messages) == 1
            stored_message = session.messages[0]
            assert stored_message.original_text == "How are you today?"
            assert stored_message.translated_text == "Wie geht es dir heute?"
            assert stored_message.audio_base64 == base64.b64encode(fake_audio).decode()


if __name__ == "__main__":
    # Tests direkt ausführen für Debugging
    pytest.main([__file__, "-v"])
