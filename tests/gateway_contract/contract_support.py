"""Constants and builders shared by the gateway contract suite."""

from __future__ import annotations

from services.api_gateway.studio_v2 import RuntimeRead
from tests.runtime_policy_helpers import runtime_read as build_runtime_read

REVISION = f"sha256:{'a' * 64}"
ALLOWED_ORIGIN = "https://translate.smart-village.solutions"
TENANT_A = "tenant-a"
TENANT_B = "tenant-b"


def runtime_read(tenant_id: str, *, storage_mode: str = "ask") -> RuntimeRead:
    return build_runtime_read(tenant_id, storage_mode, revision=REVISION)


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
