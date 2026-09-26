# Tenant Authentication Verification

Use this runbook when a tenant or an administrator is onboarded, and whenever
login succeeds but every administrative request then fails with `401` or `403`
(#363).

## What must be true for a tenant

1. Studio publishes the tenant in the login directory
   (`GET /api/login/tenants`).
2. The tenant's realm meets the SSF realm contract in
   `deploy/production/keycloak/README.md`.
3. Every administrator's access token carries the `ssf-frontend` audience, a
   well-formed and current `ssf_authorization_revision`, and the realm role
   `ssf-user`.

The gateway identifies the tenant by the realm that issued the token, matched
against the directory. A `studio_tenant_id` claim is not needed. If a token
carries one anyway, it must name the same tenant, or the token is rejected.

## Who provisions what

| Owner | Responsibility |
| --- | --- |
| Studio | Tenant realm, `ssf-frontend` client and mappers, the SSF IAM projection that sets `ssf_authorization_revision`, the `ssf-user` role assignment, Keycloak read-back, directory publication (sva-studio#1319, #1325, #1480) |
| SSF | The gateway's acceptance rules and the realm contract in this repository |

**Never fix a tenant by editing Keycloak mappers or user attributes by hand**,
in the admin console or with `kcadm.sh`. The edit bypasses Studio's read-back,
the next projection overwrites it, and it hides the defect Studio has to fix.
Report the audit output to the Studio owners instead.

## Every production command targets the production stack

```bash
source scripts/lib/production-common.sh
```

`production_compose` is `docker compose --project-name ssf-backend --env-file
.env --file deploy/production/docker-compose.production.yml`. A bare
`docker compose` on the production host targets the development stack.

## Onboarding verification

### 1. Audit every published tenant

`scripts/tenant-auth-audit.py` is read-only: it sends GET requests only, follows
no redirect, refuses plain `http://` to any host but this machine, and prints no
usernames, emails, tokens or claim values. It needs a Keycloak admin access
token. Obtain one without printing it or passing the password as a command
argument (arguments are visible in `ps`), and run the audit immediately:
master-realm tokens expire after about a minute.

```bash
source scripts/lib/production-common.sh
admin_user="$(production_compose exec -T keycloak printenv KC_BOOTSTRAP_ADMIN_USERNAME)"
admin_password="$(production_compose exec -T keycloak printenv KC_BOOTSTRAP_ADMIN_PASSWORD)"
KEYCLOAK_AUDIT_ADMIN_TOKEN="$(printf '%s' "$admin_password" | curl -fsS \
  --data-urlencode grant_type=password --data-urlencode client_id=admin-cli \
  --data-urlencode "username=$admin_user" --data-urlencode "password@-" \
  "https://auth.dialog.kassel.de/realms/master/protocol/openid-connect/token" \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["access_token"])')"
unset admin_user admin_password
SSF_AUDIT_BASE_URL=https://ssf.smart-village.solutions \
KEYCLOAK_AUDIT_BASE_URL=https://auth.dialog.kassel.de \
KEYCLOAK_AUDIT_ADMIN_TOKEN="$KEYCLOAK_AUDIT_ADMIN_TOKEN" \
  python3 scripts/tenant-auth-audit.py
unset KEYCLOAK_AUDIT_ADMIN_TOKEN
```

Each tenant ends with `ready: yes` or `ready: no (<reason>)`, and the script
exits `0` only when every published tenant is ready. A tenant is ready when its
`ssf-frontend` client can complete the login (`login client problems: none`),
at least one user holds `ssf-user`, and every holder's token would pass the
gateway (`would_pass=yes`). Users without the role are counted as
`other users (not judged)`: a realm may hold accounts that are not SSF
administrators. `ready: no (no user holds ssf-user)` is the #363 state. Users
appear only as `user_ref`, a hash of their Keycloak ID; `tenant_ref` is the
same value the gateway logs.

The audit judges claims from the tokens themselves, so claims Studio supplies
through client scopes count. The required role and the audience default to
`ssf-user` and `ssf-frontend`; set `KEYCLOAK_REQUIRED_ROLE` and
`KEYCLOAK_AUDIENCE` exactly as the gateway has them if they differ.

The audit decodes a Keycloak *example* token for each user, so it reports what
a fresh login would receive. It cannot check that the revision is *current*
against Studio's runtime configuration; step 2 covers that.

`GET failed: HTTP 401` means the admin token expired: obtain a new one and
rerun. `GET failed: HTTP 403` means the token lacks realm-admin rights.
`refusing redirect` or `refusing non-https URL` means a base URL is wrong:
the audit never lets the admin token follow a redirect or leave over plain
http.

### 2. Prove it end to end with fresh tokens

Log in at `/login` as one administrator of each of two tenants, in private
browser windows, and copy each access token into a shell variable without
pasting it anywhere else. Then:

```bash
SSF_SMOKE_BASE_URL=https://ssf.smart-village.solutions \
SSF_TENANT_A_TOKEN="$token_a" SSF_TENANT_B_TOKEN="$token_b" \
  python3 scripts/tenant-isolation-smoke.py
unset token_a token_b
```

`Tenant isolation smoke passed` proves that both tokens create sessions, see
their own sessions and are denied each other's. A failure names its cause:

| Message | Meaning |
| --- | --- |
| `Tenant A token lacks ssf_authorization_revision` | Studio's SSF IAM projection did not run for that user |
| `... has a malformed ssf_authorization_revision` | the attribute holds something other than `sha256:` and 64 lowercase hex digits |
| `... lacks the ssf-user realm role` | the role is not assigned, directly or through a group |
| `... carries a stale ssf_authorization_revision` | the revision differs from the tenant's current runtime configuration |
| `... session creation failed with HTTP 401` | see the reason code in the gateway log |

## Diagnosing "login works, every administrative request fails"

The client response is deliberately neutral. The gateway logs one line per
rejected token and counts it by reason:

```bash
production_compose logs --since 30m api_gateway | grep ssf_auth_rejected
production_compose exec -T prometheus wget -qO- \
  'http://127.0.0.1:9090/api/v1/query?query=sum%20by%20(reason)%20(increase(gateway_auth_rejections_total%5B1h%5D))'
```

A line reads `ssf_auth_rejected reason=<code> status=<status> tenant_ref=<ref>
correlation_id="<id>"`. The `correlation_id` is the request's
`X-Correlation-Id` when the caller sent a valid one, so a browser request can
be matched to its log line; it is JSON-quoted because the caller chooses it.
`missing_bearer` is logged at INFO, every other reason at WARNING: a request
with no token at all is ordinary anonymous traffic. No token content is ever
logged.

| `reason` | Status | Meaning | Owner |
| --- | --- | --- | --- |
| `revision_missing` | 401 | the token has no `ssf_authorization_revision` | Studio projection (#1325, #1480) |
| `revision_malformed` | 401 | the revision is not `sha256:` plus 64 lowercase hex digits | Studio projection |
| `role_missing` | 403 | the token lacks `ssf-user` | Studio role assignment |
| `tenant_claim_mismatch` | 401 | the token's `studio_tenant_id` names another tenant than its realm, for example a mapper left over from diagnosis | Studio realm baseline |
| `legacy_tenant_claim` | 401 | the token carries a retired `tenant_id` or `studio_instance_id` claim | Studio realm baseline |
| `unknown_issuer` | 401 | the issuing realm is not in the directory, or `KEYCLOAK_BASE_URL` does not match the token's issuer origin | Studio directory / SSF configuration |
| `directory_unavailable` | 503 | the gateway cannot read the login directory | Studio service token or directory endpoint |
| `signing_keys_unavailable` | 401 | Keycloak discovery or key fetch failed | Keycloak reachability |
| `unknown_signing_key` | 401 | the token's key ID is not published, typically right after a key rotation | Keycloak; retry after the five-minute key cache expires |
| `invalid_signing_key`, `invalid_signature` | 401 | the key or signature is not valid | investigate; possible forged token |
| `token_expired` | 401 | the access token expired | frontend token refresh |
| `invalid_audience`, `invalid_issuer`, `missing_required_claim`, `invalid_token`, `unsupported_token_header`, `malformed_token` | 401 | the token is not a valid `ssf-frontend` access token | the caller |
| `missing_bearer` | 401 | no bearer token was sent | the caller or frontend |
| `gateway_auth_misconfigured` | 401 | `KEYCLOAK_BASE_URL` is not an origin-only URL | SSF configuration |

A `502` with `studio_runtime_authorization_mismatch` on session creation is not
an authentication rejection: the token is valid, but its revision differs from
the tenant's runtime configuration. Studio has to re-project the revision.

## Confirming a fix

Tokens keep the claims they were issued with until they expire. After Studio
fixes a tenant, log out and in again, then repeat the audit and the smoke test.
Record only redacted evidence: reason codes, `would_pass` flags, the smoke
result.

## How production realm state is provisioned and reviewed

Production Keycloak runs `start --optimized` without `--import-realm`, so no
realm is provisioned from this repository. Studio provisions every tenant realm
and is the only provisioning path. The repository's
`deploy/production/keycloak/ssf-realm.json` is the SSF contract those realms
must meet, not a copy of live state.

Review production realm state by running the audit above, and through the
protected two-realm acceptance in sva-studio#1350, which verifies a fresh token
from the directory through the tenant realm to an accepted SSF request.
