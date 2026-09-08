# Administrative access transition

Use `https://translate.smart-village.solutions/login` for the new Keycloak
login. Operators manually create staff users in realm `ssf` and assign the
realm role `ssf-user`.

The legacy `/admin` password entry remains temporarily available only when
`SSF_ENABLE_LEGACY_ADMIN_ACCESS=true` is set for the API gateway and
`SSF_LEGACY_ADMIN_ACCESS_CODE` matches the legacy frontend build value. This
mechanism is not secure: the value is delivered in browser code and can be
recovered by a visitor. Set `SSF_ENABLE_LEGACY_ADMIN_ACCESS=false` to disable
it without a code change, then remove the legacy route in a follow-up release.

Before enabling the new route in production, verify a Keycloak user with
`ssf-user` can log in at `/login` and make an administrative request. Verify a
user without that role receives 403 and a request without credentials receives
401. Verify the QR join route remains available without Keycloak login.

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
X-Studio-Instance-Id: tenant-kassel
X-Correlation-Id: local-test-correlation-id
```

`Bearer studio-mock-authorized-token` has
`ssf.runtime-configuration.read`; `Bearer studio-mock-unauthorized-token`
models an authenticated caller without that permission. `tenant-kassel`
returns storage mode `ask`; `tenant-fulda` returns `disabled`. Send
`X-Mock-Scenario: authorization-pending` or `unavailable` to exercise `409`
or `503`. Send an unknown Studio instance ID to exercise `404`.
Every error response has the Studio V1 `contractVersion` and `error` envelope
documented in the mock's OpenAPI description.

The mock contains only fixed, non-sensitive test data, but it requires the V1
mock service token and is intentionally not publicly reachable. Do not use it
as a production Studio service.
