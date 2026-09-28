"""Request, response and error models of the conversation message endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc_now() -> str:
    return utc_now().isoformat()


class TextMessageRequest(BaseModel):
    """Request-Model für Text-Input"""

    text: str = Field(..., min_length=1, max_length=500, description="Text content to translate")
    source_lang: str = Field(..., description="Source language code")
    target_lang: str = Field(..., description="Target language code")

    @field_validator("text")
    @classmethod
    def validate_text_content(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Text content cannot be empty")
        return v.strip()


class MessageResponse(BaseModel):
    """Unified Response-Model für Message-Endpunkt"""

    status: str = Field(..., description="Request status")
    message_id: str = Field(..., description="Unique message identifier")
    session_id: str = Field(..., description="Session identifier")

    # Message Content
    original_text: str = Field(..., description="Original/ASR text")
    translated_text: str = Field(..., description="Translated text")

    # Audio Information
    audio_available: bool = Field(..., description="Whether audio is available")
    audio_url: Optional[str] = Field(None, description="URL to audio file if available")

    # Processing Information
    processing_time_ms: int = Field(..., description="Total processing time in milliseconds")
    pipeline_type: str = Field(..., description="Pipeline used (audio or text)")

    # Language Information
    source_lang: str = Field(..., description="Source language")
    target_lang: str = Field(..., description="Target language")

    # Timestamps
    timestamp: str = Field(..., description="Message timestamp (ISO format)")

    # Pipeline Metadata (optional, for debugging/monitoring)
    pipeline_metadata: Optional[Dict[str, Any]] = Field(
        None, description="Detailed pipeline processing metadata"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "success",
                "message_id": "msg_12345",
                "session_id": "ABC123",
                "original_text": "Hallo, wie kann ich helfen?",
                "translated_text": "Hello, how can I help?",
                "audio_available": True,
                "audio_url": ("/api/admin/session/ABC12345/audio/msg_12345/translated.wav"),
                "processing_time_ms": 2500,
                "pipeline_type": "audio",
                "source_lang": "de",
                "target_lang": "en",
                "timestamp": "2025-09-28T14:30:00Z",
            }
        }
    )


class ErrorResponse(BaseModel):
    """Error-Response-Model"""

    status: str = Field(default="error", description="Error status")
    error_code: str = Field(..., description="Error code")
    error_message: str = Field(..., description="Human-readable error message")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional error details")
    timestamp: str = Field(..., description="Error timestamp")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "error",
                "error_code": "SESSION_NOT_FOUND",
                "error_message": "Session not found or expired",
                "details": {"session_id": "ABC123"},
                "timestamp": "2025-09-28T14:30:00Z",
            }
        }
    )


# Unterstützte Sprachen basierend auf TTS-Service
SUPPORTED_LANGUAGES: Dict[str, Dict[str, str]] = {
    "de": {"name": "Deutsch", "native": "Deutsch"},
    "en": {"name": "English", "native": "English"},
    "ar": {"name": "Arabic", "native": "العربية"},
    "tr": {"name": "Turkish", "native": "Türkçe"},
    "ru": {"name": "Russian", "native": "Русский"},
    "uk": {"name": "Ukrainian", "native": "Українська"},
    "am": {"name": "Amharic", "native": "አማርኛ"},
    "ti": {"name": "Tigrinya", "native": "ትግርኛ"},
    "ku": {"name": "Kurdish", "native": "Kurmancî"},
    "fa": {"name": "Persian", "native": "فارسی"},
}


def create_error_response(
    error_code: str, error_message: str, details: Dict[str, Any]
) -> Dict[str, Any]:
    """Standardisierte Error-Response erstellen"""
    return ErrorResponse(
        error_code=error_code,
        error_message=error_message,
        details=details,
        timestamp=iso_utc_now(),
    ).model_dump()
