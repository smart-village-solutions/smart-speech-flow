# Tester release check

Proves on production that operators in two tenants can hold conversations at
the same time without seeing each other's data, and that a conversation keeps
its audio and messages only when the guest consented and the tenant stores
content. It creates four conversations and terminates all of them, whatever
happens. It never creates, changes or deletes an account.

## Before the run

1. **No live conversations.** The gateway ends a tenant's other live
   conversations when a new one starts (unless `SSF_ALLOW_PARALLEL_SESSIONS` is
   set), so run the check only when nobody is using either tenant. The check
   verifies this itself and stops, creating nothing, if either tenant has a
   live conversation.
2. **Storage mode.** In each tenant's SSF configuration in Studio, note the
   conversation-content storage mode (`ask` or `disabled`). Pass it as
   `SSF_RC_TENANT_{A,B}_STORAGE`.
3. **Tester accounts.** In each tenant's Studio user management
   (`https://<tenant>.dialog.kassel.de/`), create two regular users named
   `ssf-release-check-<yyyymmdd>-<n>`. Give each a permanent password (not
   temporary) and no required actions. They need no SSF role.
4. Keep the passwords in your shell only. Do not write them to a file.

## Run

From the repository root, with the development environment installed:

    export SSF_RC_API_BASE=https://ssf.smart-village.solutions
    export SSF_RC_KEYCLOAK_BASE=https://auth.dialog.kassel.de
    export SSF_RC_FRONTEND_ORIGIN=https://dialog.kassel.de
    export SSF_RC_TENANT_A_ID=tenant-kassel SSF_RC_TENANT_A_LANGUAGE=en SSF_RC_TENANT_A_STORAGE=ask
    export SSF_RC_TENANT_B_ID=smart-city-labor SSF_RC_TENANT_B_LANGUAGE=tr SSF_RC_TENANT_B_STORAGE=ask
    export SSF_RC_TENANT_A_USER_1=… SSF_RC_TENANT_A_PASSWORD_1=…   # and _2, and tenant B
    export SSF_RC_REPORT=release-check-report.json                 # optional
    python -m scripts.release_check

The exit code is 0 only when every check passed. It is 2 for a configuration
error, which names the variable but never its value.

## Reading the report

The report is printed as a Markdown table, and written as JSON when
`SSF_RC_REPORT` is set. It holds no password, token, message text or session
id; sessions appear as 12-character hashes, as in the gateway logs.

| Check group | Meaning |
|---|---|
| `A1 login` … `B2 login` | Keycloak login through the real login form |
| `A has no live conversations` | nobody is using the tenant, so the run cannot end a real conversation |
| `A1 create session` … `guest message 2 delivered` | one full conversation; each message reaches the other participant over WebSocket |
| `A1 → B1 … is not found` | a foreign session looks exactly like a missing one |
| `… selector … is rejected` | a request cannot choose its tenant |
| `A1 keeps 4 messages`, `A2 keeps 0 messages`, `… audio … answers` | consent-gated retention after termination |
| `… cleanup` | only when a conversation had not been terminated yet |

## After the run

Delete the four `ssf-release-check-<yyyymmdd>-<n>` users in Studio, and
confirm they no longer appear.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `A has no live conversations` fails | someone is using the tenant; wait until it is idle |
| `A1 guest reads pending session` fails with 404 for one operator per tenant | the gateway allows one live conversation per tenant, so the second operator's session ended the first |
| `Keycloak requires an action from this user` | the user has a temporary password or another required action |
| `Keycloak rejected the credentials` | wrong password, or the user is in the other tenant |
| `… socket acknowledged` fails with `rejected` | the WebSocket origin is not allowed; `SSF_RC_FRONTEND_ORIGIN` must be the production frontend |
| `… message … delivered` fails, or HTTP 503 on send | translation or TTS is down; check `/health` |
| `A1 keeps 0 messages … is the tenant's storage mode really ask?` | the tenant's storage mode is `disabled`; re-run with the right `…_STORAGE` |
