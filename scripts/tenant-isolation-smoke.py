#!/usr/bin/env python3
"""Credential-safe production smoke test for the tenant boundary."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from typing import NamedTuple

import httpx


class SmokeSettings(NamedTuple):
    base_url: str
    tenant_a_token: str
    tenant_b_token: str

    @classmethod
    def from_environment(
        cls, source: Mapping[str, str] | None = None
    ) -> "SmokeSettings":
        values = os.environ if source is None else source
        required = {
            "SSF_SMOKE_BASE_URL": values.get("SSF_SMOKE_BASE_URL", "").strip(),
            "SSF_TENANT_A_TOKEN": values.get("SSF_TENANT_A_TOKEN", "").strip(),
            "SSF_TENANT_B_TOKEN": values.get("SSF_TENANT_B_TOKEN", "").strip(),
        }
        if any(not value for value in required.values()):
            raise ValueError("Missing required smoke configuration")
        return cls(
            base_url=required["SSF_SMOKE_BASE_URL"].rstrip("/"),
            tenant_a_token=required["SSF_TENANT_A_TOKEN"],
            tenant_b_token=required["SSF_TENANT_B_TOKEN"],
        )


class SmokeFailure(RuntimeError):
    pass


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Correlation-Id": "tenant-smoke"}


def _request(
    client: httpx.Client, method: str, path: str, *, token: str | None = None
) -> httpx.Response:
    try:
        return client.request(method, path, headers=_headers(token) if token else None)
    except httpx.HTTPError:
        raise SmokeFailure("Smoke request failed") from None


def _create_session(client: httpx.Client, token: str) -> str:
    response = _request(client, "POST", "/api/admin/session/create", token=token)
    if response.status_code != 201:
        raise SmokeFailure("Session creation failed")
    session_id = response.json().get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise SmokeFailure("Session creation returned an invalid response")
    return session_id


def _assert_own_session(client: httpx.Client, token: str, session_id: str) -> None:
    response = _request(
        client, "GET", f"/api/admin/session/{session_id}/status", token=token
    )
    if response.status_code != 200:
        raise SmokeFailure("Own-tenant session lookup failed")


def _assert_cross_tenant_404(
    client: httpx.Client, token: str, session_id: str
) -> None:
    response = _request(
        client, "GET", f"/api/admin/session/{session_id}/status", token=token
    )
    if response.status_code != 404 or response.json().get("detail") != "Session not found":
        raise SmokeFailure("Cross-tenant lookup was not neutrally denied")


def _assert_customer_join(client: httpx.Client, session_id: str) -> None:
    response = _request(client, "GET", f"/api/customer/session/{session_id}")
    if response.status_code != 200:
        raise SmokeFailure("Customer capability lookup failed")


def _terminate(client: httpx.Client, token: str, session_id: str) -> None:
    response = _request(
        client, "DELETE", f"/api/admin/session/{session_id}/terminate", token=token
    )
    if response.status_code != 200:
        raise SmokeFailure("Smoke session cleanup failed")


def run_smoke(
    settings: SmokeSettings, *, transport: httpx.BaseTransport | None = None
) -> None:
    created: list[tuple[str, str]] = []
    with httpx.Client(
        base_url=settings.base_url, timeout=20, transport=transport
    ) as client:
        try:
            session_a = _create_session(client, settings.tenant_a_token)
            created.append((settings.tenant_a_token, session_a))
            session_b = _create_session(client, settings.tenant_b_token)
            created.append((settings.tenant_b_token, session_b))

            _assert_own_session(client, settings.tenant_a_token, session_a)
            _assert_own_session(client, settings.tenant_b_token, session_b)
            _assert_cross_tenant_404(client, settings.tenant_a_token, session_b)
            _assert_cross_tenant_404(client, settings.tenant_b_token, session_a)
            _assert_customer_join(client, session_a)
            _assert_customer_join(client, session_b)
        finally:
            cleanup_failed = False
            for token, session_id in created:
                try:
                    _terminate(client, token, session_id)
                except SmokeFailure:
                    cleanup_failed = True
            if cleanup_failed and sys.exc_info()[0] is None:
                raise SmokeFailure("Smoke session cleanup failed")

    print("Tenant isolation smoke passed")


def main() -> int:
    try:
        run_smoke(SmokeSettings.from_environment())
    except (SmokeFailure, ValueError):
        print("Tenant isolation smoke failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
