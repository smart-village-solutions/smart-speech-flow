#!/usr/bin/env python3
"""Read-only audit: would each published tenant's tokens pass the SSF gateway?

Discovers tenants from the public login directory, checks each realm's
`ssf-frontend` client against the SSF auth contract, and reduces a Keycloak
example access token per user to yes/no flags. It sends GET requests only and
prints no usernames, emails, tokens or claim values. It never repairs anything:
tenant realms and their token contents are provisioned by Studio (#363,
sva-studio#1325, #1480).

Environment:
  SSF_AUDIT_BASE_URL          SSF origin serving /api/login/tenants
  KEYCLOAK_AUDIT_BASE_URL     Keycloak origin of the tenant realms
  KEYCLOAK_AUDIT_ADMIN_TOKEN  admin access token, obtained out of band

Exit status: 0 when every published tenant and user would pass, 1 otherwise,
2 when the configuration is incomplete.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from ssf_auth_contract import (  # noqa: E402
    has_realm_role,
    is_secure_url,
    login_client_problems,
    token_flags,
    unverified_claims,
)

_DEFAULT_AUDIENCE = "ssf-frontend"
_DEFAULT_ROLE = "ssf-user"
_PAGE_SIZE = 100
_TIMEOUT_SECONDS = 15.0
# The same width as the gateway's tenant_ref, so audit output and
# `ssf_auth_rejected` log lines can be matched.
_TENANT_REF_LENGTH = 12
_USER_REF_LENGTH = 10


class AuditError(RuntimeError):
    pass


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """urllib copies every non-content header, Authorization included, onto a
    redirected request, even to plain http. The audit carries an admin token,
    so it follows no redirect at all."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        raise AuditError(f"refusing redirect (HTTP {code})")


def _require_safe_url(url: str) -> None:
    if not is_secure_url(url):
        raise AuditError("refusing non-https URL")


class ReadOnlyHttp:
    """The audit's only way out: a JSON GET over https, and nothing else."""

    def __init__(self, opener: Callable[..., Any] | None = None) -> None:
        self._opener = opener or urllib.request.build_opener(_RefuseRedirects).open

    def _open(self, request: urllib.request.Request) -> Any:
        if request.get_method() != "GET":
            raise AuditError("refusing non-GET request")
        _require_safe_url(request.full_url)
        return self._opener(request, timeout=_TIMEOUT_SECONDS)

    def get_json(self, url: str, headers: Mapping[str, str]) -> Any:
        request = urllib.request.Request(url, headers=dict(headers), method="GET")
        try:
            with self._open(request) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            raise AuditError(f"GET failed: HTTP {error.code}") from None
        except (urllib.error.URLError, ValueError) as error:
            raise AuditError(f"GET failed: {type(error).__name__}") from None


@dataclass
class UserReport:
    user_ref: str
    administrator: bool
    flags: dict[str, bool]


@dataclass
class TenantReport:
    tenant_ref: str
    realm: str
    login_problems: list[str] = field(default_factory=list)
    users: list[UserReport] = field(default_factory=list)
    error: str | None = None


@dataclass(frozen=True)
class _Target:
    """What the gateway requires, as configured for it."""

    tenant_id: str
    audience: str
    role: str


def _ref(value: str, length: int) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def _example_claims(body: Any) -> Mapping[str, Any]:
    """Keycloak returns the example token as a claims object; accept a JWT too."""
    if isinstance(body, dict) and isinstance(body.get("access_token"), str):
        return unverified_claims(body["access_token"]) or {}
    if isinstance(body, str):
        return unverified_claims(body) or {}
    return body if isinstance(body, dict) else {}


class _RealmReader:
    def __init__(self, http: ReadOnlyHttp, keycloak_base_url: str, realm: str, token: str):
        self._http = http
        self._base = f"{keycloak_base_url}/admin/realms/{urllib.parse.quote(realm, safe='')}"
        self._headers = {"Authorization": f"Bearer {token}"}

    def get(self, path: str, **query: str) -> Any:
        suffix = f"?{urllib.parse.urlencode(query)}" if query else ""
        return self._http.get_json(f"{self._base}{path}{suffix}", self._headers)

    def user_ids(self) -> list[str]:
        ids: list[str] = []
        while True:
            page = self.get(
                "/users", briefRepresentation="true", first=str(len(ids)), max=str(_PAGE_SIZE)
            )
            ids.extend(str(user["id"]) for user in page)
            if not page:
                return ids


def _user_report(
    reader: _RealmReader, client_uuid: str, user_id: str, target: _Target
) -> UserReport:
    # The example token is what a fresh login would receive, so it includes
    # claims from client scopes as well as the client's own mappers.
    body = reader.get(
        f"/clients/{urllib.parse.quote(client_uuid, safe='')}"
        "/evaluate-scopes/generate-example-access-token",
        userId=user_id,
        scope="openid",
    )
    claims = _example_claims(body)
    flags = token_flags(
        claims, tenant_id=target.tenant_id, audience=target.audience, role=target.role
    )
    return UserReport(
        user_ref=_ref(user_id, _USER_REF_LENGTH),
        administrator=has_realm_role(claims, target.role),
        flags=flags,
    )


def _audit_tenant(reader: _RealmReader, target: _Target, report: TenantReport) -> None:
    clients = reader.get("/clients", clientId=target.audience)
    client = clients[0] if clients else None
    report.login_problems = login_client_problems(client, target.tenant_id)
    if client is None:
        return
    report.users = [
        _user_report(reader, str(client["id"]), user_id, target) for user_id in reader.user_ids()
    ]


def audit(
    http: ReadOnlyHttp,
    *,
    ssf_base_url: str,
    keycloak_base_url: str,
    admin_token: str,
    audience: str = _DEFAULT_AUDIENCE,
    role: str = _DEFAULT_ROLE,
) -> list[TenantReport]:
    directory = http.get_json(f"{ssf_base_url.rstrip('/')}/api/login/tenants", {})
    reports = []
    for tenant in directory.get("tenants", []):
        tenant_id, realm = str(tenant.get("id", "")), str(tenant.get("realm", ""))
        report = TenantReport(tenant_ref=_ref(tenant_id, _TENANT_REF_LENGTH), realm=realm)
        reader = _RealmReader(http, keycloak_base_url.rstrip("/"), realm, admin_token)
        try:
            _audit_tenant(reader, _Target(tenant_id, audience, role), report)
        except AuditError as error:
            report.error = str(error)
        except (KeyError, TypeError, AttributeError) as error:
            report.error = f"unexpected response: {type(error).__name__}"
        reports.append(report)
    return reports


def not_ready_reason(report: TenantReport, role: str = _DEFAULT_ROLE) -> str | None:
    """Why a tenant cannot yet be used for SSF administration, or None if it can.

    Only users holding the required role are SSF administrators; the realm's
    other users are listed but never judged.
    """
    if report.error:
        return report.error
    if report.login_problems:
        return f"login client: {', '.join(report.login_problems)}"
    administrators = [user for user in report.users if user.administrator]
    if not administrators:
        return f"no user holds {role}"
    rejected = sum(not user.flags["would_pass"] for user in administrators)
    if rejected:
        return f"{rejected} of {len(administrators)} {role} holders would be rejected"
    return None


def exit_code(reports: list[TenantReport], role: str = _DEFAULT_ROLE) -> int:
    ready = all(not_ready_reason(report, role) is None for report in reports)
    return 0 if reports and ready else 1


def _render_tenant(report: TenantReport, role: str) -> list[str]:
    lines = [f"tenant_ref={report.tenant_ref} realm={report.realm}"]
    if report.error:
        return [*lines, f"  error: {report.error}"]
    lines.append(f"  login client problems: {', '.join(report.login_problems) or 'none'}")
    administrators = [user for user in report.users if user.administrator]
    lines.append(f"  {role} holders: {len(administrators)}")
    for user in administrators:
        flags = " ".join(f"{name}={'yes' if value else 'no'}" for name, value in user.flags.items())
        lines.append(f"    user_ref={user.user_ref} {flags}")
    lines.append(f"  other users (not judged): {len(report.users) - len(administrators)}")
    lines.append("  revision freshness: not checked (needs Studio runtime credentials)")
    reason = not_ready_reason(report, role)
    lines.append(f"  ready: {'yes' if reason is None else 'no (' + reason + ')'}")
    return lines


def render(reports: list[TenantReport], role: str = _DEFAULT_ROLE) -> str:
    if not reports:
        return "no tenant is published in the login directory"
    return "\n".join(line for report in reports for line in _render_tenant(report, role))


def main() -> int:
    names = ("SSF_AUDIT_BASE_URL", "KEYCLOAK_AUDIT_BASE_URL", "KEYCLOAK_AUDIT_ADMIN_TOKEN")
    settings = {name: os.environ.get(name, "").strip() for name in names}
    if not all(settings.values()):
        print(f"Set {', '.join(names)}", file=sys.stderr)
        return 2
    # The same variables and defaults the gateway reads.
    role = os.environ.get("KEYCLOAK_REQUIRED_ROLE", _DEFAULT_ROLE).strip() or _DEFAULT_ROLE
    audience = os.environ.get("KEYCLOAK_AUDIENCE", _DEFAULT_AUDIENCE).strip() or _DEFAULT_AUDIENCE
    try:
        reports = audit(
            ReadOnlyHttp(),
            ssf_base_url=settings["SSF_AUDIT_BASE_URL"],
            keycloak_base_url=settings["KEYCLOAK_AUDIT_BASE_URL"],
            admin_token=settings["KEYCLOAK_AUDIT_ADMIN_TOKEN"],
            audience=audience,
            role=role,
        )
    except (AuditError, AttributeError) as error:
        print(f"Tenant auth audit failed: {error}", file=sys.stderr)
        return 1
    print(render(reports, role))
    return exit_code(reports, role)


if __name__ == "__main__":
    raise SystemExit(main())
