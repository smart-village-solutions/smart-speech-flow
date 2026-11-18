"""Recording permissions are read from the verified token (spec §14)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from services.api_gateway.recording.permissions import (
    CUSTODIAN,
    REQUEST,
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
