# Change: Add the signed Studio tenant context

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

