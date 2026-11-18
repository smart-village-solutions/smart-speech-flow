"""Closed wire contracts for the Studio recording lifecycle API."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool
from pydantic.alias_generators import to_camel

Identifier = Annotated[
    str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]
Subject = Annotated[str, Field(min_length=1, max_length=255)]


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, alias_generator=to_camel)


class PrepareOrg(StrictBody):
    public_key: str = Field(min_length=87, max_length=87)
    expected_active_key_id: Identifier | None


class Activate(StrictBody):
    proof: str = Field(min_length=43, max_length=43)
    saved_confirmation: StrictBool


class PrepareTransfer(StrictBody):
    conversation_ids: list[Identifier] = Field(min_length=1, max_length=100)
    organisation_key_id: Identifier
    target_user_sub: Subject
    expected_target_key_version: int = Field(gt=0, le=2147483647)
    expected_target_fingerprint: str = Field(min_length=43, max_length=43)
    reason: str = Field(min_length=1, max_length=1000)


class EnvelopeFields(StrictBody):
    v: int = Field(ge=1, le=1)
    ephemeral: str = Field(alias="R", min_length=87, max_length=87)
    nonce: str = Field(min_length=16, max_length=16)
    ct: str = Field(min_length=64, max_length=64)


class Envelope(EnvelopeFields):
    t: Literal["SSF-CK-WRAP-V2"]


class Submission(StrictBody):
    conversation_id: Identifier
    key_id: Identifier
    envelope: Envelope


class Commit(StrictBody):
    proof: str = Field(min_length=43, max_length=43)
    wraps: list[Submission] = Field(min_length=1, max_length=1000)


class Challenge(EnvelopeFields):
    t: Literal["SSF-ORG-POSSESSION-V1"]


class OrganisationKey(StrictBody):
    key_id: Identifier
    version: int
    public_key: str
    fingerprint: str
    state: Literal["prepared", "active", "superseded"]
    created_at: str
    activated_at: str | None


class Registry(StrictBody):
    keys: list[OrganisationKey]
    active_key_id: Identifier | None


class PreparedKey(StrictBody):
    preparation_id: Identifier
    key_id: Identifier
    version: int
    fingerprint: str
    expires_at: str
    challenge_envelope: Challenge


class TargetKey(StrictBody):
    user_sub: Subject
    version: int
    fingerprint: str
    enc_pub: str
    sig_pub: str


class KeyScope(StrictBody):
    key_id: Identifier
    organisation_key_id: Identifier


class Candidate(StrictBody):
    conversation_id: Identifier
    employee_sub: Subject
    started_at: str
    ended_at: str
    key_ids: list[Identifier]
    organisation_key_ids: list[Identifier]
    key_scopes: list[KeyScope]


class Candidates(StrictBody):
    items: list[Candidate]
    next_cursor: str | None


class SourceWrap(StrictBody):
    envelope: Envelope
    signature: str


class Signer(StrictBody):
    key_id: str
    public_key: str


class SourceKey(StrictBody):
    conversation_id: Identifier
    key_id: Identifier
    epoch: int
    source_wrap: SourceWrap
    source_signer: Signer


class PreparedTransfer(StrictBody):
    transfer_id: Identifier
    scope_digest: str
    expires_at: str
    organisation_key: OrganisationKey
    target_key: TargetKey
    challenge_envelope: Challenge
    keys: list[SourceKey]


class TransferReceipt(StrictBody):
    transfer_id: Identifier
    status: Literal["committed"]
    target_user_sub: Subject
    target_key_version: int
    scope_digest: str
    granted_key_ids: list[Identifier]
    committed_at: str


class ErrorDetail(StrictBody):
    error_code: str = Field(alias="error_code")
    message: str


class ErrorResponse(StrictBody):
    detail: ErrorDetail


class PersonalVersion(StrictBody):
    version: int
    state: Literal["active", "superseded", "revoked", "left"]
    fingerprint: str
    enc_pub: str
    sig_pub: str
    created_at: str


class VersionCatalog(StrictBody):
    versions: list[PersonalVersion]
    active_version: int | None


class PersonalBlob(PersonalVersion):
    blob: str


class Signers(StrictBody):
    keys: list[Signer]
