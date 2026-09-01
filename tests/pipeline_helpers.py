"""Shared fixtures for the gateway pipeline suites (#189 non-blocking, #191 bound).

Both suites drive the same four handlers with the same fake requests. Keeping the
builders here stops the two files from drifting apart as the handlers change.

Not named ``test_*``, so pytest does not collect it.
"""

import importlib
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, Mock

from services.api_gateway.session_manager import SessionStatus

# routes/__init__.py re-exports the endpoint functions under their module names,
# so `routes.upload` is the handler rather than the module. Import by path.
upload_route = importlib.import_module("services.api_gateway.routes.upload")
pipeline_route = importlib.import_module("services.api_gateway.routes.pipeline")
health_route = importlib.import_module("services.api_gateway.routes.health")

AUDIO_BYTES = b"RIFF" + b"fake_wav_audio_data" + b"\x00" * 100

PIPELINE_SUCCESS: Dict[str, Any] = {
    "error": False,
    "asr_text": "Guten Tag",
    "translation_text": "Good day",
    "audio_bytes": b"fake_output_audio",
}

TEXT_PIPELINE_SUCCESS: Dict[str, Any] = {
    "error": False,
    "translation_text": "Guten Tag",
    "audio_bytes": b"fake_output_audio",
    "debug": {},
}

# Generous: every assertion in these suites is about ordering, thread identity or
# rejection, never about how long something took.
SAFETY_TIMEOUT = 15.0


async def make_active_session(manager) -> str:
    """An ACTIVE admin session whose customer speaks English.

    Admin sends de -> en, which is what the request builders below produce; a
    mismatch trips validate_session_languages before the pipeline is reached.
    """
    session_id = await manager.create_admin_session()
    session = manager.get_session(session_id)
    session.status = SessionStatus.ACTIVE
    session.customer_language = "en"
    return session_id


def request_with(admission: Optional[Any] = None) -> Mock:
    """A fake request whose app state carries ``admission``.

    ``None`` leaves the handler unbounded, which is what the non-blocking suite
    wants and what any route reached before lifespan startup gets.
    """
    request = Mock()
    request.app.state.pipeline_admission = admission
    return request


def audio_request(admission: Optional[Any] = None) -> Mock:
    request = request_with(admission)
    request.headers = {"content-type": "multipart/form-data; boundary=boundary"}
    request.form = AsyncMock(
        return_value={
            "file": upload_file(),
            "source_lang": "de",
            "target_lang": "en",
            "client_type": "admin",
        }
    )
    return request


def text_request(admission: Optional[Any] = None) -> Mock:
    request = request_with(admission)
    request.headers = {"content-type": "application/json"}
    request.json = AsyncMock(
        return_value={
            "text": "Guten Tag",
            "source_lang": "de",
            "target_lang": "en",
            "client_type": "admin",
        }
    )
    return request


def upload_file() -> Mock:
    """Stands in for an UploadFile the handlers only ever ``await .read()`` on."""
    handle = Mock()
    handle.read = AsyncMock(return_value=AUDIO_BYTES)
    return handle


def legacy_pipeline_request(admission: Optional[Any] = None) -> Mock:
    """The /pipeline handler also reads query params and origin headers."""
    request = request_with(admission)
    request.query_params = {}
    request.headers = {}
    return request
