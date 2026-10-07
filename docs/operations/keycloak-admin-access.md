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

## 27 September 2026 gateway promotion

The compatible gateway consumer is running as `prod-4447d3c`, built from
source revision `4447d3cf86a53e1e49574a54ed901dddf7669e87` with image ID
`sha256:da2b30f5dbba52a9a501eb3bd49935cf7b61b4950fd486ebf4466de878ca7768`.
The production health check passed, the public login directory listed two
realms, and unauthenticated admin-history and feedback reads returned 401.
The prior `prod-74cb49a` image remains the rollback target. These checks do
not replace the protected fresh-token two-realm acceptance in Studio #1350;
no approved test tokens were available during this promotion. Studio must
continue emitting legacy claims until the consumer migration is verified.

## Local Studio Runtime Configuration mock

The `studio-mock` service is an opt-in contract-testing dependency for the
Studio--SSF runtime configuration API, contract versions 1 and 2, and the
installation content API (contract version 2). Start it explicitly:

```bash
docker compose --profile studio-mock up --build studio-mock
```

It listens only on loopback at `http://127.0.0.1:8010`. SSF containers on the
same Compose network use `http://studio-mock:8000` as their base URL. Configure
the consumer through `STUDIO_RUNTIME_CONFIGURATION_BASE_URL`; the clients add
the contract paths themselves, so replacing the mock with Studio requires only
a base-URL change. The mock serves:

- `/internal/plugins/ssf/v2/runtime-configuration`
- `/internal/plugins/ssf/v2/installation-content`
- `/internal/plugins/ssf/v1/admin-login-tenants`

Runtime configuration requests require these headers:

```text
Authorization: Bearer studio-mock-authorized-token
X-Studio-Tenant-Id: tenant-kassel
X-Correlation-Id: local-test-correlation-id
```

Installation content and the login directory take the same headers without
`X-Studio-Tenant-Id`.

`Bearer studio-mock-authorized-token` has
`ssf.runtime-configuration.read`; `Bearer studio-mock-unauthorized-token`
models an authenticated caller without that permission. `tenant-kassel`
returns storage mode `ask`; `tenant-fulda` returns `disabled`. On v2,
`tenant-kassel` keeps conversation content for 4320 hours, `tenant-fulda` has
no retention and no storage questions, and `tenant-marburg` returns
`retentionHours: 0`. `tenant-marburg` has no local Keycloak realm, so the login
directory lists only Kassel and Fulda.

On both runtime paths, send `X-Mock-Scenario: suspended`, `plugin-inactive`,
`tenant-not-ready`, or `unavailable` to exercise the exact `409` and `503`
contract envelopes. A scenario applies to any tenant ID, so it takes precedence
over the unknown-tenant check. Send an unknown tenant ID without a scenario to
exercise `404`. A missing `X-Studio-Tenant-Id` or `X-Correlation-Id`, a legacy
header (`X-Studio-Instance-Id` or `X-Tenant-Id`) or any query selector is
rejected with `404 tenant_not_found`, as Studio does.

On v2, `storage-disabled` turns the tenant's storage mode to `disabled` for
that request, and `invalid-content` adds a feedback question of an unsupported
type to the first guest language: the runtime body keeps a valid storage policy
and SSF drops only that guest language.

Installation content ignores the tenant scenarios (`suspended`,
`plugin-inactive`, `tenant-not-ready` and `storage-disabled`) and answers them
with `200`. It answers `400 malformed_request` to a missing `X-Correlation-Id`,
a tenant header (`X-Studio-Tenant-Id`, `X-Studio-Instance-Id` or `X-Tenant-Id`)
or a query, `503 installation_content_unavailable` to `unavailable`, and with
`invalid-content` keeps everything but its feedback form.

The login directory answers `404 tenant_not_found` to a missing
`X-Correlation-Id`, a tenant header or a query, and
`503 admin_login_directory_unavailable` to `unavailable`.

Every error response has the Studio `contractVersion` and `error` envelope
documented in the mock's OpenAPI description, with `contractVersion` `1.0` on
v1 paths and `2.0` on v2 paths.

The v2 bodies live in `services/studio_mock/fixtures/` without a revision;
`services/studio_mock/contract_fixtures.py` loads them and stamps
`configurationRevision` as the SHA-256 of their canonical JSON.

The mock contains only fixed, non-sensitive test data, but it requires the
mock service token and is intentionally not publicly reachable. Do not use it
as a production Studio service.
