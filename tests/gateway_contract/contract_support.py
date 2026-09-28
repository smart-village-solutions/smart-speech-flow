"""Constants and builders shared by the gateway contract suite."""

from __future__ import annotations

from services.api_gateway.studio_runtime_client import RuntimeConfiguration

REVISION = f"sha256:{'a' * 64}"
ALLOWED_ORIGIN = "https://translate.smart-village.solutions"
TENANT_A = "tenant-a"
TENANT_B = "tenant-b"


def runtime_configuration(tenant_id: str, *, storage_mode: str = "ask") -> RuntimeConfiguration:
    return RuntimeConfiguration.model_validate(
        {
            "contractVersion": "1.0",
            "configurationRevision": REVISION,
            "authorizationRevision": REVISION,
            "tenant": {"id": tenant_id, "displayName": tenant_id, "timeZone": "Europe/Berlin"},
            "branding": {"logo": None, "icon": None},
            "localization": {
                "defaultLocale": "de-DE",
                "locales": [
                    {
                        "locale": "de-DE",
                        "authenticatedHomeExplanationHtml": "<p>Admin</p>",
                        "guestExplanationHtml": "<p>Guest</p>",
                        "conversationContentStorageQuestionHtml": (
                            "<p>Store?</p>" if storage_mode == "ask" else None
                        ),
                    }
                ],
            },
            "conversationContentStorage": {"mode": storage_mode},
        }
    )


def wav_bytes(seconds: float = 1.0, rate: int = 16000) -> bytes:
    import io
    import math
    import struct
    import wave

    frames = b"".join(
        struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * index / rate)))
        for index in range(int(seconds * rate))
    )
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(frames)
    return buffer.getvalue()
