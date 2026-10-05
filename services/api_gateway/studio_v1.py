"""Transport, envelope and status dispatch shared by the Studio V1 clients.

Each client keeps only its own contract: path, success models, the error codes
each status may carry, and its error subclass and code prefix (#346).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Protocol, TypeVar

import aiohttp
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .origin import parse_origin

M = TypeVar("M", bound=BaseModel)


class ContractModel(BaseModel):
    """Validate known fields while accepting optional V1 extensions."""

    model_config = ConfigDict(extra="allow", strict=True, populate_by_name=True)


class StudioV1ErrorDetails(ContractModel):
    """The stable nested error object in Studio's V1 error envelope."""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=200)
    retryable: bool
    correlation_id: str = Field(alias="correlationId", min_length=1, max_length=128)


class StudioV1ErrorEnvelope(ContractModel):
    """The stable Studio V1 error response shape."""

    contract_version: str = Field(alias="contractVersion", pattern="^1[.]0$")
    error: StudioV1ErrorDetails


class StudioV1ClientError(RuntimeError):
    """Safe failure surfaced by a Studio V1 client; never carries Studio content."""

    def __init__(self, code: str, *, retryable: bool, status: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.status = status


@dataclass(frozen=True)
class StudioV1HttpResponse:
    status: int
    payload: Mapping[str, Any] | None  # None: the body was not a JSON object


class StudioV1Transport(Protocol):
    async def get(
        self, url: str, headers: Mapping[str, str], timeout_seconds: float
    ) -> StudioV1HttpResponse:
        raise NotImplementedError


class AiohttpStudioV1Transport:
    async def get(
        self, url: str, headers: Mapping[str, str], timeout_seconds: float
    ) -> StudioV1HttpResponse:
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                try:
                    payload = await response.json()
                except (aiohttp.ContentTypeError, ValueError):
                    payload = None
                if not isinstance(payload, Mapping):
                    payload = None
                return StudioV1HttpResponse(status=response.status, payload=payload)


def is_printable_ascii(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and all(32 <= ord(character) <= 126 for character in value)
    )


def require_printable_ascii(value: str, name: str) -> None:
    if not is_printable_ascii(value) or len(value) > 128:
        raise ValueError(f"{name} must be printable ASCII with at most 128 characters")


class StudioV1Endpoint:
    """One fixed Studio V1 GET endpoint and the failures it may report."""

    def __init__(
        self,
        base_url: str,
        path: str,
        *,
        error_type: type[StudioV1ClientError],
        code_prefix: str,
        transport: StudioV1Transport | None,
        timeout_seconds: float,
    ) -> None:
        origin = parse_origin(base_url)
        if origin is None:
            raise ValueError("base_url must be an HTTP origin")
        if not 0 < timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be between 0 and 30")
        self.url = f"{origin}{path}"
        self._error_type = error_type
        self._prefix = code_prefix
        self._transport = transport or AiohttpStudioV1Transport()
        self._timeout_seconds = timeout_seconds

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    def _error(
        self, reason: str, *, retryable: bool = False, status: int | None = None
    ) -> StudioV1ClientError:
        return self._error_type(f"{self._prefix}_{reason}", retryable=retryable, status=status)

    async def bearer_token(self, token_provider: Callable[[], Awaitable[str]]) -> str:
        token = await token_provider()
        if not is_printable_ascii(token):
            raise self._error("token_invalid")
        return token

    async def fetch_validated(
        self,
        headers: Mapping[str, str],
        model: type[M],
        expected_codes: Mapping[int, set[str]],
    ) -> M:
        try:
            response = await self._transport.get(self.url, headers, self._timeout_seconds)
        except StudioV1ClientError:
            raise
        except (TimeoutError, asyncio.TimeoutError, aiohttp.ClientError):
            raise self._error("network_error", retryable=True) from None

        if response.payload is None:
            raise self._error("response_invalid", status=response.status)
        if response.status == 200:
            try:
                return model.model_validate(response.payload)
            except ValidationError:
                raise self._error("response_invalid", status=200) from None
        if response.status not in expected_codes:
            raise self._error(
                "unexpected_status", retryable=response.status >= 500, status=response.status
            )
        try:
            envelope = StudioV1ErrorEnvelope.model_validate(response.payload)
        except ValidationError:
            raise self._error("error_invalid", status=response.status) from None
        if envelope.error.code not in expected_codes[response.status]:
            raise self._error("error_invalid", status=response.status)
        raise self._error_type(
            envelope.error.code, retryable=envelope.error.retryable, status=response.status
        )
