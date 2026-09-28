"""Shared fixtures for the gateway pipeline suites (#189 non-blocking, #191 bound).

Both suites drive the same four handlers with the same fake requests. Keeping the
builders here stops the two files from drifting apart as the handlers change.

Not named ``test_*``, so pytest does not collect it.
"""

import importlib
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, Mock

from services.api_gateway.pipeline_logic import SpeechPipeline
from services.api_gateway.service_health import ServiceHealthManager
from services.api_gateway.session_manager import SessionStatus
from services.api_gateway.speech_services import HttpSpeechServices
from services.api_gateway.tenant_session import (
    RuntimeConfigurationSnapshot,
    TenantSessionKey,
)
from services.api_gateway.translation_refiner import (
    BaseTranslationRefiner,
    NoOpTranslationRefiner,
)

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


REVISION = f"sha256:{'a' * 64}"


def speech_pipeline(
    health: Optional[ServiceHealthManager] = None,
    refiner: Optional[BaseTranslationRefiner] = None,
) -> SpeechPipeline:
    """One app's speech pipeline, as build_gateway_dependencies builds it.

    Its own breakers unless ``health`` is given, and refinement off unless a
    ``refiner`` is, as in a process without LLM_REFINEMENT_* settings.
    """
    health = health if health is not None else ServiceHealthManager()
    return SpeechPipeline(
        speech=HttpSpeechServices(health.circuit_breakers),
        refiner=refiner if refiner is not None else NoOpTranslationRefiner(),
    )


def pipeline_collaborators(
    health: Optional[ServiceHealthManager] = None,
    refiner: Optional[BaseTranslationRefiner] = None,
) -> Dict[str, Any]:
    """The keyword arguments process_wav and process_text_pipeline take."""
    pipeline = speech_pipeline(health, refiner)
    return {"speech": pipeline.speech, "refiner": pipeline.refiner}


SNAPSHOT = RuntimeConfigurationSnapshot(REVISION, REVISION, "{}")


async def make_active_session(manager) -> TenantSessionKey:
    """An ACTIVE admin session whose customer speaks English.

    Admin sends de -> en, which is what the request builders below produce; a
    mismatch trips validate_session_languages before the pipeline is reached.
    """
    session = await manager.create_admin_session("tenant-test", SNAPSHOT)
    session.status = SessionStatus.ACTIVE
    session.customer_language = "en"
    manager.store.save(session)
    return session.key


def request_with() -> Mock:
    """A fake request. The handlers take their admission gate as an argument."""
    return Mock()


def audio_request() -> Mock:
    request = request_with()
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


def text_request() -> Mock:
    request = request_with()
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


def legacy_pipeline_request() -> Mock:
    """The /pipeline handler also reads query params and origin headers."""
    request = request_with()
    request.query_params = {}
    request.headers = {}
    return request
