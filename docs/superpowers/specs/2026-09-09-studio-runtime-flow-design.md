# Studio tenant-bound runtime flow design

## Context

Issue #298 integrates the Studio Runtime Configuration V1 consumer boundary in
SSF. The contract terminology is fixed: the signed user-token claim is
`studio_tenant_id`, the outbound header is `X-Studio-Tenant-Id`, the response
identity is `tenant.id`, and SSF uses `tenant_id` internally. Browser input,
query parameters, request bodies, and client state are not tenant trust
boundaries.

The foundations from #294--#297 are now present on `main`: the mock uses the
canonical header, `StudioTenantContext` rejects browser-controlled tenant
selectors, `StudioRuntimeTokenProvider` obtains service tokens, and
`StudioRuntimeClient` validates V1 responses. Issue #298 therefore only wires
these components together and adds the authorization-revision gate; it does
not recreate their transport, caching, or schema logic.

## Goals

- Derive one trusted SSF tenant context from a validated Studio-issued user
  token.
- Reuse the existing service-token provider and V1 client to fetch the
  tenant's validated configuration.
- Compare the configuration `authorizationRevision` with the authenticated
  user's `ssf_authorization_revision` claim and fail closed on absence or
  mismatch.
- Propagate a correlation ID to Studio and return the validated configuration
  from one integration boundary for a later session or persistence slice.
- Prove success, tenant isolation, revision mismatch, and upstream failures
  with mock-backed integration tests.

## Non-goals

- Conversation-content persistence or consent enforcement.
- Changes to the existing runtime client, token-provider cache, or V1 schema
  validation.
- Guest tenant resolution, production Keycloak-client provisioning, and UI
  language-picker changes.

## Architecture

The gateway owns the trust boundary. Its authentication dependency validates
the user JWT and constructs an immutable `TenantContext(tenant_id,
authorization_revision)`. It rejects a missing, malformed, or non-string
`studio_tenant_id` and a missing or non-string `ssf_authorization_revision`.
No route accepts a tenant selector as an alternative identity source.

`StudioTenantContext` is extended with `authorization_revision`, derived only
from the validated `ssf_authorization_revision` claim. A missing, malformed,
or conflicting claim rejects the tenant-bound operation before Studio is
called. The existing `StudioRuntimeTokenProvider.get_token` is passed directly
to the existing `StudioRuntimeClient`.

A small `StudioRuntimeFlow` integration service receives a
`StudioTenantContext`, correlation ID, and configured client. It calls
`StudioRuntimeClient.fetch(tenant_id, correlation_id)`, compares the returned
`authorizationRevision` with the context value using a constant-time string
comparison, and returns a `ValidatedRuntimeConfiguration`. This type contains
the trusted context and the already validated client response. A FastAPI
dependency constructs this object for future authenticated session and
persistence endpoints; no new public endpoint or persistence behavior is
introduced in this issue.

## Request flow

1. The gateway validates the bearer JWT signature, issuer, audience, and
   required SSF role.
2. It derives `TenantContext` exclusively from `studio_tenant_id` and
   `ssf_authorization_revision` claims.
3. The runtime-flow dependency accepts a valid incoming correlation ID or
   generates a UUID correlation ID, then forwards it to the Studio client.
4. The existing token provider supplies the service token; the existing runtime
   client sends it with `X-Studio-Tenant-Id: TenantContext.tenant_id`.
5. The client validates the successful V1 response and confirms
   `tenant.id == tenant_id`.
6. The integration service confirms the authorization revisions match, then
   returns `ValidatedRuntimeConfiguration` to downstream code.

## Error handling

Every failure is fail-closed. Missing or conflicting identity claims result in
an authentication/authorization failure before Studio is called. Token
acquisition, transport, malformed response, Studio error envelope, tenant
mismatch, missing revision, and revision mismatch result in a stable gateway
error with the correlation ID, never a default configuration. Diagnostics use
classified codes and redact bearer tokens, client secrets, and upstream
response fields that could contain sensitive material.

## Testing

Focused tests extend tenant-context claim parsing for
`ssf_authorization_revision` and exercise the integration service with the
existing client/provider seams. Mock-backed integration tests demonstrate that
a valid Kassel tenant receives Kassel configuration, a browser-provided Fulda
tenant cannot alter that selection, a returned Fulda configuration for Kassel
is rejected, and missing or mismatching authorization revisions are rejected.
They also verify correlation-ID forwarding or generation and absence of a
fallback configuration for one representative Studio failure.

## Delivery note

The current `main` branch includes the canonical mock correction and the
tenant-context, token-provider, and runtime-client foundations. #298 should
remain limited to their composition and revision gate.
