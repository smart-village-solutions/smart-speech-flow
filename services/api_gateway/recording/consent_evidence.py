"""What a guest's yes must carry, checked against the policy read at the yes (spec §6).

The text hash is compared with the text the gateway would serve now, so a
client cannot vouch for words it was never shown. On the first yes of a
conversation the guest's name, the signature (or the tap fallback) and the
employee's ID check join the record; a resume carries the text alone.
"""

from __future__ import annotations

import base64
import hmac
from dataclasses import dataclass
from typing import Any, Final

from ..studio_v2 import RecordingPolicy
from .consent_text import ConsentText, consent_text, german_text
from .session_state import RecordingState

NAME_MAX_LENGTH: Final[int] = 200
SIGNATURE_MAX_BYTES: Final[int] = 256 * 1024
_PNG_MAGIC: Final[bytes] = b"\x89PNG\r\n\x1a\n"


class ConsentEvidenceError(Exception):
    """The answer or request lacks what the policy asks for; `code` is the wire code."""

    def __init__(self, code: str, status: int = 422) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True, slots=True)
class GuestAnswer:
    """What the guest's screen sent with its answer."""

    language: str
    text_sha256: str | None = None
    name: str | None = None
    signature_png: bytes | None = None
    cannot_sign: bool = False


def decode_signature(encoded: str | None) -> bytes | None:
    """A base64 PNG of at most SIGNATURE_MAX_BYTES, or None when none was sent."""
    if encoded is None:
        return None
    try:
        png = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise ConsentEvidenceError("INVALID_SIGNATURE") from None
    if not png.startswith(_PNG_MAGIC) or len(png) > SIGNATURE_MAX_BYTES:
        raise ConsentEvidenceError("INVALID_SIGNATURE")
    return png


def evidence(policy: RecordingPolicy, asked: RecordingState, answer: GuestAnswer) -> dict[str, Any]:
    """The fields a yes adds to `consent.json`; raises when the yes must be refused."""
    kind = asked.request_kind or "first"
    served = consent_text(policy, answer.language, kind)
    if not hmac.compare_digest((answer.text_sha256 or "").encode(), served.sha256.encode()):
        raise ConsentEvidenceError("CONSENT_TEXT_MISMATCH", status=409)
    fields: dict[str, Any] = text_fields(policy, served)
    if kind == "first":
        fields["guest"] = _guest(asked.proposed_name, answer.name)
        fields["signature"] = _signature(policy, answer)
        fields["id_check"] = {
            "policy": policy.id_check,
            "checked": asked.id_checked_at is not None,
            "at": asked.id_checked_at.isoformat() if asked.id_checked_at else None,
        }
    return fields


def text_fields(policy: RecordingPolicy, served: ConsentText) -> dict[str, Any]:
    return {"text": served.record(), "text_de": german_text(policy, served).record()}


def _guest(proposed: str | None, sent: str | None) -> dict[str, str]:
    name = (sent or "").strip()
    if not name or len(name) > NAME_MAX_LENGTH:
        raise ConsentEvidenceError("NAME_REQUIRED")
    # The guest's yes confirms whichever name their screen showed.
    entered_by = "employee" if proposed is not None and name == proposed else "guest"
    return {"name": name, "entered_by": entered_by}


def _signature(policy: RecordingPolicy, answer: GuestAnswer) -> dict[str, Any]:
    if policy.signature == "off":
        return {"policy": "off", "given": False}
    if answer.signature_png is not None:
        return {
            "policy": policy.signature,
            "given": True,
            "png": base64.b64encode(answer.signature_png).decode(),
        }
    if policy.signature == "required" and not answer.cannot_sign:
        raise ConsentEvidenceError("SIGNATURE_REQUIRED")
    return {
        "policy": policy.signature,
        "given": False,
        "fallback": "tap" if answer.cannot_sign else None,
    }
