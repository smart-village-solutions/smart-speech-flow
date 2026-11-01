"""The recording-directory client accepts only a well-formed directory of the asked tenant."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from services.api_gateway.recording.directory import StudioCustodianDirectory
from services.api_gateway.studio_recording_directory_client import (
    StudioRecordingDirectoryClient,
    StudioRecordingDirectoryClientError,
)
from services.api_gateway.studio_runtime_token import StudioTokenError
from services.api_gateway.studio_v1 import StudioV1HttpResponse
from services.studio_mock import contract_fixtures

TENANT = "tenant-kassel"


class FixedTransport:
    def __init__(self, status: int, payload: Mapping[str, Any] | None) -> None:
        self.status, self.payload = status, payload
        self.headers: Mapping[str, str] = {}

    async def get(
        self, url: str, headers: Mapping[str, str], timeout_seconds: float
    ) -> StudioV1HttpResponse:
        self.headers = headers
        return StudioV1HttpResponse(self.status, self.payload)


async def _token() -> str:
    return "service-token"


def _client(transport: FixedTransport) -> StudioRecordingDirectoryClient:
    return StudioRecordingDirectoryClient("https://studio.test", _token, transport=transport)


def _body(**changes: Any) -> dict[str, Any]:
    body = contract_fixtures.recording_directory(TENANT)
    body.update(changes)
    return body


@pytest.mark.asyncio
async def test_a_valid_directory_is_read_with_the_tenant_header():
    transport = FixedTransport(200, _body())
    directory = await _client(transport).fetch(TENANT, "corr-1")

    assert transport.headers["X-Studio-Tenant-Id"] == TENANT
    custodians = directory.holders_of("ssf.recording.recovery.custodian")
    assert [user.display_name for user in custodians.values()] == [
        "Anna Becker",
        "Bernd Schulz",
        "Carla Weber",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"tenantId": "tenant-fulda"}, "studio_recording_directory_tenant_mismatch"),
        ({"contractVersion": "1.0"}, "studio_recording_directory_response_invalid"),
        ({"directoryRevision": "sha256:XYZ"}, "studio_recording_directory_response_invalid"),
    ],
)
async def test_a_directory_for_another_tenant_or_contract_is_refused(changes, code):
    with pytest.raises(StudioRecordingDirectoryClientError) as caught:
        await _client(FixedTransport(200, _body(**changes))).fetch(TENANT, "corr-1")
    assert caught.value.code == code


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_change",
    [
        {"sub": "has space"},
        {"permissions": ["ssf.configuration.tenant.manage"]},
        {"permissions": []},
        {"languages": ["Deutsch"]},
        {"displayName": ""},
    ],
)
async def test_a_malformed_user_refuses_the_whole_directory(user_change):
    body = _body()
    body["users"][0].update(user_change)
    with pytest.raises(StudioRecordingDirectoryClientError) as caught:
        await _client(FixedTransport(200, body)).fetch(TENANT, "corr-1")
    assert caught.value.code == "studio_recording_directory_response_invalid"


@pytest.mark.asyncio
async def test_a_duplicate_subject_refuses_the_directory():
    body = _body()
    body["users"].append(dict(body["users"][0]))
    with pytest.raises(StudioRecordingDirectoryClientError):
        await _client(FixedTransport(200, body)).fetch(TENANT, "corr-1")


@pytest.mark.asyncio
async def test_studio_unavailability_is_retryable():
    envelope = {
        "contractVersion": "2.0",
        "error": {
            "code": "recording_directory_unavailable",
            "message": "Recording directory is unavailable.",
            "retryable": True,
            "correlationId": "corr-1",
        },
    }
    with pytest.raises(StudioRecordingDirectoryClientError) as caught:
        await _client(FixedTransport(503, envelope)).fetch(TENANT, "corr-1")
    assert (caught.value.code, caught.value.retryable) == ("recording_directory_unavailable", True)


@pytest.mark.asyncio
async def test_custodians_are_unavailable_on_any_studio_failure_including_the_token():
    async def no_token() -> str:
        raise StudioTokenError("studio_token_unavailable", retryable=True)

    without_token = StudioRecordingDirectoryClient(
        "https://studio.test", no_token, transport=FixedTransport(200, _body())
    )
    assert await StudioCustodianDirectory(without_token).custodians(TENANT, "corr-1") is None
    refused = _client(FixedTransport(200, _body(tenantId="tenant-other")))
    assert await StudioCustodianDirectory(refused).custodians(TENANT, "corr-1") is None
    names = await StudioCustodianDirectory(_client(FixedTransport(200, _body()))).custodians(
        TENANT, "corr-1"
    )
    assert sorted(names.values()) == ["Anna Becker", "Bernd Schulz", "Carla Weber"]


@pytest.mark.asyncio
async def test_names_cover_every_recording_user_and_are_empty_when_studio_cannot_answer():
    refused = _client(FixedTransport(200, _body(tenantId="tenant-other")))
    assert await StudioCustodianDirectory(refused).names(TENANT, "corr-1") == {}
    assert await StudioCustodianDirectory(None).names(TENANT, "corr-1") == {}
    body = _body()
    names = await StudioCustodianDirectory(_client(FixedTransport(200, body))).names(
        TENANT, "corr-1"
    )
    assert names == {user["sub"]: user["displayName"] for user in body["users"]}


@pytest.mark.asyncio
async def test_members_are_every_sub_and_none_when_studio_cannot_answer():
    """A leaver list must never read a failure as an empty directory (spec §9.8)."""
    refused = _client(FixedTransport(200, _body(tenantId="tenant-other")))
    assert await StudioCustodianDirectory(refused).members(TENANT, "corr-1") is None
    assert await StudioCustodianDirectory(None).members(TENANT, "corr-1") is None
    body = _body()
    members = await StudioCustodianDirectory(_client(FixedTransport(200, body))).members(
        TENANT, "corr-1"
    )
    assert members == frozenset(user["sub"] for user in body["users"])
