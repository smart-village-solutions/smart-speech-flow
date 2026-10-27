"""Recording permissions and step-up are read from the verified token (spec §14)."""

from __future__ import annotations

import time

import pytest
from fastapi import HTTPException

from services.api_gateway.recording.permissions import (
    CUSTODIAN,
    REQUEST,
    permissions_of,
    require_permission,
    step_up_satisfied,
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


def test_step_up_needs_an_mfa_login_from_the_last_five_minutes():
    now = time.time()
    assert step_up_satisfied({"acr": "mfa", "auth_time": int(now) - 10}, now)
    assert not step_up_satisfied({"acr": "1", "auth_time": int(now) - 10}, now)
    assert not step_up_satisfied({"acr": "mfa", "auth_time": int(now) - 301}, now)
    assert not step_up_satisfied({"acr": "mfa"}, now)
    assert not step_up_satisfied({"acr": "mfa", "auth_time": True}, now)
    assert not step_up_satisfied({"acr": "mfa", "auth_time": int(now) + 61}, now)


def test_a_login_stamped_by_a_slightly_fast_keycloak_clock_counts():
    now = time.time()
    assert step_up_satisfied({"acr": "mfa", "auth_time": int(now) + 5}, now)
