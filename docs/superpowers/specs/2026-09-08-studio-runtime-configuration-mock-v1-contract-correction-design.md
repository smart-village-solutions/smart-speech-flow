# Studio Runtime Configuration Mock V1 Contract Correction Design

> **Status: Superseded historical design record.** Preserve this document as a
> record of its original proposal. The cross-system contract is pending in
> [sva-studio#1286](https://github.com/smart-village-solutions/sva-studio/issues/1286);
> the SSF mock work is tracked by the active
> `openspec/changes/add-studio-runtime-configuration-mock/` change.

## Context

The existing mock was intentionally made browser-accessible over public HTTP.
Review feedback establishes that this differs from the current Studio--SSF V1
contract: Studio instance identity, a service token with an explicit
permission, and a correlation identifier are required. The response structure
also needs authorization metadata and locale naming aligned with the contract.

## Goals

- Exercise the V1 request contract with `Authorization`,
  `X-Studio-Instance-Id`, and `X-Correlation-Id`.
- Model deterministic authentication, authorization, tenant, authorization
  projection, and dependency failures with the stable V1 error envelope.
- Return contract-correct locale fields plus deterministic SHA-256
  configuration and authorization revisions.
- Restrict the mock to opt-in, loopback-only access.

## Non-Goals

- Validate real Studio-issued tokens or call an identity provider.
- Change SSF production authentication or tenant persistence.
- Provide browser access to the protected internal endpoint.

## Decisions

### Request authentication and identity

The mock accepts two fixed service tokens. `Bearer
studio-mock-authorized-token` has `ssf.runtime-configuration.read` and is the
only token that can receive a configuration. `Bearer
studio-mock-unauthorized-token` represents an authenticated caller without
that permission. A missing or unknown token produces `401
SERVICE_UNAUTHENTICATED`; the known unauthorized token produces `403
SERVICE_FORBIDDEN`.

`X-Studio-Instance-Id` is the sole tenant selector. `X-Correlation-Id` is
required and echoed in every error envelope. Missing either required header
produces a stable `400` envelope. The removed `tenantId` query parameter is
not interpreted.

### Response and revisions

Configuration fixtures use `localization.defaultLocale`,
`localization.locales`, and each locale's `locale` property. The effective
configuration excluding `configurationRevision` is serialized deterministically
with sorted keys and compact separators, then SHA-256 hashed. The mock uses
the same deterministic process for the authorization fixture excluding
`authorizationRevision`; both values are emitted as `sha256:` followed by 64
lowercase hexadecimal characters.

### Failure simulation

`X-Mock-Scenario: authorization-pending` returns `409
AUTHORIZATION_PROJECTION_PENDING`. `X-Mock-Scenario: unavailable` returns
`503 RUNTIME_CONFIGURATION_UNAVAILABLE`. An unknown Studio instance returns
`404 TENANT_NOT_FOUND`. These, authentication, authorization, and missing
header failures share the V1 `contractVersion` and `error` envelope.

### Exposure

The `studio-mock` Compose service remains opt-in but binds only to
`127.0.0.1:8010`. It has no Traefik labels and no public HTTP route. The
runbook describes local internal-contract requests rather than browser URLs.

## Risks and Mitigations

- Fixed tokens might be mistaken for production credentials: use clearly
  mock-specific values and document that no real token validation occurs.
- Revision drift: contract tests recompute both hashes from the returned
  canonical payloads.
- Consumers relying on the temporary query parameter: remove it deliberately
  and test that identity only comes from the required header.

## Migration Plan

1. Replace the query/header compatibility tests with the V1 request contract.
2. Update mock fixtures, endpoint behavior, OpenAPI, and runbook together.
3. Rebuild and restart only the opt-in mock profile; verify it binds to
   loopback and returns a configuration for the authorized request.

## Open Questions

None. The fixed-token mapping is intentionally local to this mock.
