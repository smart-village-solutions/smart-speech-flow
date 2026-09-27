# Administrative access

`/login` is the administrative entry point. Staff choose their organisation
there and sign in through that tenant's Keycloak realm. For conversation
access, the gateway validates the token signature, RS256 algorithm, expiry,
audience, non-empty subject, and issuer against exactly one admitted Studio
login-directory entry. It derives the tenant from that entry; it does not
require `ssf-user`, `studio_tenant_id`, `ssf_authorization_revision`,
`ssf_permissions`, or `ssf_roles` in the user token. Legacy claims, if present,
cannot select another tenant.

Feedback-reading endpoints and the telemetry probe retain a separate
`ssf-user` role check. Runtime configuration is still fetched for the derived
tenant, and its tenant ID must match; the token's old authorization revision
is no longer compared with the runtime configuration revision.

The temporary `/admin` password entry and the `X-SSF-Legacy-Access` header were
removed in #216. `/admin` now returns the normal not-found page, and the gateway
ignores the header. `SSF_ENABLE_LEGACY_ADMIN_ACCESS`,
`SSF_LEGACY_ADMIN_ACCESS_CODE` and `FRONTEND_DEMO_PASSWORD` are no longer read
and can be deleted from existing environment files.

After release, verify fresh attribute-free user tokens from two admitted realms
can each create, read, and terminate only their own conversations over HTTP,
polling, and WebSocket. Confirm an unadmitted realm, invalid token, or
cross-tenant session access is denied, and an attribute-free user cannot read
feedback or emit a telemetry probe. A request without a bearer token still
receives 401 even when it carries `X-SSF-Legacy-Access`; the QR join route
remains available without a Keycloak login. Deploy this gateway consumer
before removing the legacy claims and roles from token production. Do not
close the rollout issues based on CI alone; record the live two-realm checks.

Disabling an account prevents new login. Already issued access tokens are
validated locally by the gateway and can remain usable until their short
expiry; this change does not provide instant revocation or token introspection.

## Local Studio Runtime Configuration mock

The `studio-mock` service is an opt-in contract-testing dependency for the
Studio--SSF Runtime Configuration V1 API. Start it explicitly:

```bash
docker compose --profile studio-mock up --build studio-mock
```

It listens only on loopback at `http://127.0.0.1:8010`. SSF containers on the
same Compose network use `http://studio-mock:8000` as their base URL. Configure
the consumer through `STUDIO_RUNTIME_CONFIGURATION_BASE_URL` and retain the
path `/internal/plugins/ssf/v1/runtime-configuration`; replacing the mock with
Studio then requires only a base-URL change.

Every request requires these headers:

```text
Authorization: Bearer studio-mock-authorized-token
X-Studio-Tenant-Id: tenant-kassel
X-Correlation-Id: local-test-correlation-id
```

`Bearer studio-mock-authorized-token` has
`ssf.runtime-configuration.read`; `Bearer studio-mock-unauthorized-token`
models an authenticated caller without that permission. `tenant-kassel`
returns storage mode `ask`; `tenant-fulda` returns `disabled`. Send
`X-Mock-Scenario: suspended`, `plugin-inactive`, `tenant-not-ready`, or
`unavailable` to exercise the exact `409` and `503` contract envelopes. Send
an unknown tenant ID to exercise `404`. Legacy headers (`X-Studio-Instance-Id`
and `X-Tenant-Id`) and all query selectors are deliberately rejected.
Every error response has the Studio V1 `contractVersion` and `error` envelope
documented in the mock's OpenAPI description.

The mock contains only fixed, non-sensitive test data, but it requires the V1
mock service token and is intentionally not publicly reachable. Do not use it
as a production Studio service.
