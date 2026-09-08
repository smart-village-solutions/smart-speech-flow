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

The `studio-mock` service is a local contract-testing dependency for the
Studio--SSF Runtime Configuration V1 API. Start it explicitly:

```bash
docker compose --profile studio-mock up --build studio-mock
```

It listens only on `127.0.0.1:8010`. Request
`/internal/plugins/ssf/v1/runtime-configuration` with bearer token
`studio-mock-service-token`, `X-Tenant-Id` set to `tenant-kassel` or
`tenant-fulda`, and a correlation ID. `tenant-kassel` returns storage mode
`ask`; `tenant-fulda` returns `disabled`. Send `X-Mock-Scenario: not-ready`
or `unavailable` to exercise the `409` or `503` error envelopes.
Omit the bearer token, use a wrong token, or send an unknown tenant ID to
exercise the `401`, `403`, or `404` envelopes. Every error response has the
Studio V1 `contractVersion` and `error` envelope documented in the mock's
OpenAPI description.

The `studio-mock` profile must not be enabled in production. It contains only
fixed test data and does not validate real Studio service credentials.
