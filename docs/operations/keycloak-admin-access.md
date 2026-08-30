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
