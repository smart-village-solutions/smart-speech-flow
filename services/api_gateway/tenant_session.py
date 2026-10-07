"""Tenant-bound session identifiers."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass

from .session_pseudonym import tenant_ref as pseudonymous_tenant_ref

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
        return pseudonymous_tenant_ref(self.tenant_id)
