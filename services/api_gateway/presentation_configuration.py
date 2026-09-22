"""The storage-policy-free projection of a validated Studio configuration.

A session stores this rather than the full contract model so that nothing in
the persistence path can read an authorisation out of frozen session state.
Only a live Studio read may authorise a write.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from .studio_runtime_client import Branding, ContractModel, Localization, Tenant


class PresentationConfiguration(ContractModel):
    """Everything a session needs in order to render, and nothing more."""

    contract_version: str = Field(alias="contractVersion", pattern="^1[.]0$")
    configuration_revision: str = Field(alias="configurationRevision")
    authorization_revision: str = Field(alias="authorizationRevision")
    tenant: Tenant
    branding: Branding
    localization: Localization

    @model_validator(mode="before")
    @classmethod
    def reject_storage_policy(cls, value: Any) -> Any:
        """Refuse a snapshot that still carries a policy, rather than restore it.

        Rejected by name, not with extra="forbid": ContractModel allows unknown
        keys because Contract V1 requires tolerance of optional additions.
        """
        if isinstance(value, dict) and (
            "conversationContentStorage" in value or "conversation_content_storage" in value
        ):
            raise ValueError("a presentation snapshot carries no storage policy")
        return value
