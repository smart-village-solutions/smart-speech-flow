# Change: Add the signed Studio tenant context

> Contract update (2026-09-27): the claim-derived tenant requirement below is
> superseded for conversation access by
> `update-realm-derived-conversation-access` (#438). The verified issuer and
> unique Studio directory entry now establish the tenant.

## Why

Tenant-bound SSF operations need one server-side tenant identity derived from
the already validated Studio-issued user token. Browser-controlled tenant
selectors must never become an alternative trust boundary.

## What Changes

- Validate the canonical signed `studio_tenant_id` claim.
- Expose the validated value internally as an immutable `tenant_id` context.
- Reject missing, malformed, legacy, or conflicting tenant claims.
- Reject tenant selectors supplied through query parameters, JSON request
  bodies, headers, or cookies.
- Add focused positive and negative tests.

## Impact

- Affected specs: `studio-tenant-context`
- Affected code: API-gateway authentication dependencies
- Follow-up: #298 wires the context into tenant-bound runtime flows.
