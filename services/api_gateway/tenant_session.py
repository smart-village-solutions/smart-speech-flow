"""Tenant-bound identifiers and immutable runtime-configuration snapshots."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from hashlib import sha256

from .studio_runtime_client import RuntimeConfiguration

SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


@dataclass(frozen=True, slots=True)
class TenantSessionKey:
    """The complete internal identity of a conversation session."""

    tenant_id: str
    session_id: str

    def __post_init__(self) -> None:
        if not self.tenant_id or len(self.tenant_id) > 128:
            raise ValueError("tenant_id must contain 1..128 characters")
        if not SESSION_ID_PATTERN.fullmatch(self.session_id):
            raise ValueError("invalid session_id")

    @property
    def redis_tenant_component(self) -> str:
        encoded = base64.urlsafe_b64encode(self.tenant_id.encode("utf-8"))
        return encoded.decode("ascii").rstrip("=")

    @property
    def tenant_ref(self) -> str:
        return sha256(self.tenant_id.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True, slots=True)
class RuntimeConfigurationSnapshot:
    """Canonical, immutable snapshot of one validated Studio configuration."""

    configuration_revision: str
    authorization_revision: str
    canonical_json: str

    @classmethod
    def from_configuration(
        cls, value: RuntimeConfiguration
    ) -> RuntimeConfigurationSnapshot:
        payload = value.model_dump(mode="json", by_alias=True)
        return cls(
            configuration_revision=value.configuration_revision,
            authorization_revision=value.authorization_revision,
            canonical_json=json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )

    @classmethod
    def from_dict(cls, value: dict[str, str]) -> RuntimeConfigurationSnapshot:
        return cls(
            configuration_revision=value["configuration_revision"],
            authorization_revision=value["authorization_revision"],
            canonical_json=value["canonical_json"],
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "configuration_revision": self.configuration_revision,
            "authorization_revision": self.authorization_revision,
            "canonical_json": self.canonical_json,
        }

    def to_configuration(self) -> RuntimeConfiguration:
        return RuntimeConfiguration.model_validate_json(self.canonical_json)
