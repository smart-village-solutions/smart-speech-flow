# Administrative access

`/login` is the only administrative entry point. Staff choose their
organisation there and sign in through that tenant's Keycloak realm; Studio
provisions the realms, the `ssf-user` role and the staff accounts.

The temporary `/admin` password entry and the `X-SSF-Legacy-Access` header were
removed in #216. `/admin` now returns the normal not-found page, and the gateway
ignores the header. `SSF_ENABLE_LEGACY_ADMIN_ACCESS`,
`SSF_LEGACY_ADMIN_ACCESS_CODE` and `FRONTEND_DEMO_PASSWORD` are no longer read
and can be deleted from existing environment files.

After a release that touches authentication, verify that a user with `ssf-user`
can log in at `/login` and make an administrative request, that a user without
that role receives 403, that a request without a bearer token receives 401 even
when it carries `X-SSF-Legacy-Access`, and that the QR join route remains
available without a Keycloak login.

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
