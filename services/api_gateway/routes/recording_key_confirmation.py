"""The mailed link of a re-enrolment (spec §9.9): no login, the token is the authority.

Outside /api/admin on purpose: the link is opened from a mail app, often on a
phone where nobody is signed in. The tenant comes from the token, never from
the request.
"""

from __future__ import annotations

from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from ..dependencies import optional_container
from ..recording.crypto.encoding import b64url
from ..recording.crypto.transcript import display_fingerprint
from ..recording.key_confirmation import KeyConfirmationError, KeyConfirmations
from ..recording.permissions import coded
from ..value_free_validation import ValueFreeValidationRoute

router = APIRouter(
    prefix="/api/recording/key-confirmation",
    tags=["recording"],
    route_class=ValueFreeValidationRoute,
)

_ANSWERS: Final[dict[str, tuple[int, str]]] = {
    "link_invalid": (404, "LINK_INVALID"),
    "link_expired": (410, "LINK_EXPIRED"),
    "ceremony_in_progress": (409, "CEREMONY_IN_PROGRESS"),
    "unavailable": (503, "RECORDING_UNAVAILABLE"),
}


def get_key_confirmations(request: Request) -> KeyConfirmations:
    service: KeyConfirmations | None = getattr(
        optional_container(request), "recording_key_confirmations", None
    )
    if service is None:
        raise coded(503, "RECORDING_UNAVAILABLE", "Recording is not available")
    return service


Confirmations = Annotated[KeyConfirmations, Depends(get_key_confirmations)]


class LinkBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 32 bytes, base64url without padding.
    token: str = Field(min_length=43, max_length=43)


def _refused(error: KeyConfirmationError) -> Exception:
    status_code, code = _ANSWERS[error.code]
    return coded(status_code, code, "The link was refused")


@router.post("/lookup")
async def lookup_link(body: LinkBody, service: Confirmations) -> dict[str, Any]:
    try:
        details = await service.lookup(body.token)
    except KeyConfirmationError as error:
        raise _refused(error) from None
    return {
        "fingerprint": b64url(details.fingerprint),
        "fingerprint_display": display_fingerprint(details.fingerprint),
        "requested_at": details.requested_at.isoformat(),
        "expires_at": details.expires_at.isoformat(),
    }


@router.post("/confirm")
async def confirm_link(body: LinkBody, service: Confirmations) -> dict[str, str]:
    try:
        fingerprint = await service.confirm(body.token)
    except KeyConfirmationError as error:
        raise _refused(error) from None
    return {
        "fingerprint": b64url(fingerprint),
        "fingerprint_display": display_fingerprint(fingerprint),
    }


@router.post("/decline", status_code=status.HTTP_204_NO_CONTENT)
async def decline_link(body: LinkBody, service: Confirmations) -> Response:
    try:
        await service.decline(body.token)
    except KeyConfirmationError as error:
        raise _refused(error) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
