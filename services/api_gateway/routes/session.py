# services/api_gateway/routes/session.py
"""The supported-language list the frontends read."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from ..message_models import SUPPORTED_LANGUAGES

router = APIRouter()


@router.get("/languages/supported")
async def get_supported_languages() -> Dict[str, Any]:
    """Verfügbare Sprachen für Frontends"""
    return {
        "languages": SUPPORTED_LANGUAGES,
        "admin_default": "de",
        "popular": ["en", "ar", "tr", "ru", "fa"],  # Häufige Verwaltungssprachen
    }
