"""Settings for the tester release check, read from the environment.

An error names the variable and never its value: the value may be a password.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import quote

STORAGE_MODES = ("ask", "disabled")
GUEST_LANGUAGES = ("en", "tr")


class ConfigError(ValueError):
    """A setting is missing or invalid."""


@dataclass(frozen=True)
class Operator:
    username: str
    password: str = field(repr=False)


@dataclass(frozen=True)
class Tenant:
    label: str
    directory_id: str
    guest_language: str
    storage_mode: str
    operators: tuple[Operator, Operator]


@dataclass(frozen=True)
class Settings:
    api_base: str
    keycloak_base: str
    frontend_origin: str
    client_id: str
    tenants: tuple[Tenant, Tenant]

    @property
    def websocket_base(self) -> str:
        scheme, rest = self.api_base.split("://", 1)
        return f"{'wss' if scheme == 'https' else 'ws'}://{rest}"

    def redirect_uri(self, tenant: Tenant) -> str:
        """The frontend's own login callback, the only redirect the client allows."""
        return f"{self.frontend_origin}/login/{quote(tenant.directory_id, safe='')}"

    def secrets(self) -> list[str]:
        return [operator.password for tenant in self.tenants for operator in tenant.operators]


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is not set")
    return value


def _url(env: Mapping[str, str], name: str) -> str:
    value = _required(env, name).rstrip("/")
    if not value.startswith(("https://", "http://")):
        raise ConfigError(f"{name} must be an http(s) URL")
    return value


def _choice(env: Mapping[str, str], name: str, default: str, allowed: tuple[str, ...]) -> str:
    value = env.get(name, "").strip() or default
    if value not in allowed:
        raise ConfigError(f"{name} must be one of: {', '.join(allowed)}")
    return value


def _operator(env: Mapping[str, str], prefix: str, number: int) -> Operator:
    return Operator(
        username=_required(env, f"{prefix}USER_{number}"),
        password=_required(env, f"{prefix}PASSWORD_{number}"),
    )


def _tenant(env: Mapping[str, str], label: str, default_language: str) -> Tenant:
    prefix = f"SSF_RC_TENANT_{label}_"
    return Tenant(
        label=label,
        directory_id=_required(env, f"{prefix}ID"),
        guest_language=_choice(env, f"{prefix}LANGUAGE", default_language, GUEST_LANGUAGES),
        storage_mode=_choice(env, f"{prefix}STORAGE", "ask", STORAGE_MODES),
        operators=(_operator(env, prefix, 1), _operator(env, prefix, 2)),
    )


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    source = os.environ if env is None else env
    tenants = (_tenant(source, "A", "en"), _tenant(source, "B", "tr"))
    if tenants[0].directory_id == tenants[1].directory_id:
        raise ConfigError("SSF_RC_TENANT_A_ID and SSF_RC_TENANT_B_ID must differ")
    return Settings(
        api_base=_url(source, "SSF_RC_API_BASE"),
        keycloak_base=_url(source, "SSF_RC_KEYCLOAK_BASE"),
        frontend_origin=_url(source, "SSF_RC_FRONTEND_ORIGIN"),
        client_id=source.get("SSF_RC_CLIENT_ID", "").strip() or "ssf-frontend",
        tenants=tenants,
    )
