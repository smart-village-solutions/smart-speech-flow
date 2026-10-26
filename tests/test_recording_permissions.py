"""Recording permissions and step-up are read from the verified token (spec §14)."""

from __future__ import annotations

import time

import pytest
from fastapi import HTTPException

from services.api_gateway.recording.permissions import (
    CUSTODIAN,
    REQUEST,
    STEP_UP_ACR_ENV,
    STEP_UP_MAX_AGE_ENV,
    StepUpPolicy,
    permissions_of,
    require_permission,
)


@pytest.mark.parametrize(
    ("claim", "expected"),
    [
        ([REQUEST, CUSTODIAN], {REQUEST, CUSTODIAN}),
        ([REQUEST, 7, None], {REQUEST}),
        ("ssf.recording.request", set()),
        (None, set()),
    ],
)
def test_permissions_come_only_from_a_list_of_strings(claim, expected):
    assert permissions_of({"ssf_permissions": claim}) == expected


async def test_another_recording_permission_does_not_admit():
    dependency = require_permission(CUSTODIAN)
    with pytest.raises(HTTPException) as refused:
        await dependency(claims={"ssf_permissions": [REQUEST]})
    assert refused.value.detail["error_code"] == "PERMISSION_REQUIRED"
    holder = {"ssf_permissions": [REQUEST, CUSTODIAN]}
    assert await dependency(claims=holder) is holder


def test_step_up_needs_the_configured_acr_and_a_fresh_login(monkeypatch):
    monkeypatch.delenv(STEP_UP_ACR_ENV, raising=False)
    monkeypatch.delenv(STEP_UP_MAX_AGE_ENV, raising=False)
    policy = StepUpPolicy.from_environment()
    now = time.time()
    assert policy.satisfied_by({"acr": "mfa", "auth_time": int(now) - 10}, now)
    assert not policy.satisfied_by({"acr": "1", "auth_time": int(now) - 10}, now)
    assert not policy.satisfied_by({"acr": "mfa", "auth_time": int(now) - 301}, now)
    assert not policy.satisfied_by({"acr": "mfa"}, now)
    assert not policy.satisfied_by({"acr": "mfa", "auth_time": True}, now)
    assert not policy.satisfied_by({"acr": "mfa", "auth_time": int(now) + 60}, now)


def test_step_up_settings_are_bounded(monkeypatch):
    monkeypatch.setenv(STEP_UP_ACR_ENV, "gold, mfa")
    monkeypatch.setenv(STEP_UP_MAX_AGE_ENV, "86400")
    policy = StepUpPolicy.from_environment()
    assert policy.acr_values == {"gold", "mfa"}
    assert policy.max_age_seconds == 300
