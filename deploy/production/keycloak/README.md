# SSF realm contract

`ssf-realm.json` is the reviewed statement of what a tenant realm must provide
for the SSF gateway to accept its tokens. It is also the realm the development
`docker-compose.yml` imports.

- Public client `ssf-frontend`: Standard Flow with PKCE S256, no secret, no
  implicit flow, no direct-access grants, redirects only to `/login/*` of the
  frontend origin over HTTPS.
- The `ssf-frontend` audience in the access token.
- An `ssf_authorization_revision` claim in the access token. The mapper here
  has the shape Studio provisions; what the gateway needs is the claim, not
  that particular mapper.
- The realm role `ssf-user`.

It deliberately has **no** `studio_tenant_id` mapper. The gateway identifies the
tenant by the realm that issued the token, matched against the Studio login
directory, and rejects a token whose `studio_tenant_id` disagrees with that
tenant (#363). It has no users.

`scripts/lib/ssf_auth_contract.py` encodes the same list.
`tests/operations/test_keycloak_realm.py` fails when this file stops meeting it,
and `scripts/tenant-auth-audit.py` checks live realms against it.

## Production

Production never imports this file. Keycloak runs `start --optimized` without
`--import-realm`, and the tenant realms, the `ssf-frontend` client, its mappers,
the revision attribute and the role assignments are provisioned by Studio
(sva-studio#1319, #1325). Do not repair a production realm by editing mappers
or user attributes by hand: that bypasses Studio's read-back and the next
projection overwrites it. Review production realm state with the read-only
audit in `docs/operations/runbooks/tenant-auth-verification.md`.

## Local development

The realm name `ssf` does not match the realms the Studio mock publishes
(`kassel-ssf-2025`, `fulda-ssf-2025`), and the realm has no users, so a stack
that imports only this file cannot complete an administrative login. Local
administrative work uses realm fixtures that match the mock's directory.
