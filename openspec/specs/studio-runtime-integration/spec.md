# studio-runtime-integration Specification

## Purpose
Defines how SSF reads Studio contract v2: the runtime configuration and installation content clients, the strict policy view and lenient content parsing, accepted contract versions, and the one shared runtime token.

## Requirements

### Requirement: Studio Runtime Configuration V2 client

SSF SHALL read tenant runtime configuration from
`/internal/plugins/ssf/v2/runtime-configuration` with a service bearer token,
`X-Studio-Tenant-Id` and `X-Correlation-Id`. It SHALL accept any
`contractVersion` `2.x` body and SHALL reject a body whose `tenant.id` differs
from the requested tenant. Error envelopes with `contractVersion` `1.x` or
`2.x` SHALL be mapped to the same error codes as in v1.

#### Scenario: Valid v2 response

- **WHEN** Studio answers 200 with a `2.0` body for the requested tenant
- **THEN** SSF returns the storage policy and the parsed content

#### Scenario: Tenant mismatch

- **WHEN** the body's `tenant.id` differs from `X-Studio-Tenant-Id`
- **THEN** SSF treats the read as failed

#### Scenario: v2 error envelope

- **WHEN** Studio answers 409 with `contractVersion` `2.0` and code
  `tenant_suspended`
- **THEN** SSF reports a tenant-availability conflict, as it did for v1

### Requirement: Separate parsing of policy and content

SSF SHALL validate the storage policy (`contractVersion`,
`configurationRevision`, `tenant`, `conversationContentStorage`) separately
from content. An invalid policy SHALL fail the read. An invalid content section
SHALL be dropped and logged without failing the read; an invalid guest language
SHALL be dropped on its own.

`retentionHours` SHALL be an integer from 0 to 8760 when the mode is `ask` and
null when the mode is `disabled`.

#### Scenario: Unknown feedback question type

- **WHEN** a guest language's feedback form contains a question type SSF does
  not support
- **THEN** that guest language is dropped from content
- **AND THEN** the storage policy is still used for consent and persistence

#### Scenario: Invalid storage policy

- **WHEN** `mode` is `ask` and `retentionHours` is null
- **THEN** the read fails and persistence is refused

### Requirement: Studio installation content client

SSF SHALL read installation content from
`/internal/plugins/ssf/v2/installation-content` with a service bearer token and
`X-Correlation-Id`, without a tenant header. The installation feedback form
SHALL be parsed with the same rules as tenant feedback forms.

#### Scenario: Installation content available

- **WHEN** Studio answers 200 with a valid body
- **THEN** SSF holds its branding, legal URLs, start page and login texts and
  feedback form

#### Scenario: Installation content unavailable

- **WHEN** the read fails and no earlier content is held
- **THEN** SSF reports the content as unavailable without affecting sessions

### Requirement: One shared Studio service token

SSF SHALL obtain Studio service tokens through one provider shared by the
runtime, installation and login-directory clients.

#### Scenario: Concurrent reads

- **WHEN** the runtime and directory clients need a token at the same time
- **THEN** at most one token request is made and both use the result
