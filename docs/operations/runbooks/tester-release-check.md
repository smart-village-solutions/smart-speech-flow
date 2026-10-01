# Tester release check

Proves on production that operators in two tenants can hold conversations at
the same time without seeing each other's data, and that a conversation keeps
its audio and messages only when the guest consented and the tenant stores
content. It creates four conversations and terminates all of them, whatever
happens. It never creates, changes or deletes an account.

## Before the run

1. **No live conversations.** Run the check only when nobody is using either
   tenant, so its conversations and load never mix with real ones. The check
   itself cannot see other admins' conversations, because each admin sees only
   their own (#476), so confirm it on the host. This prints the id of every
   tenant with a live conversation; neither `SSF_RC_TENANT_A_ID` nor
   `SSF_RC_TENANT_B_ID` may appear (other tenants do not matter):

       source scripts/lib/production-common.sh
       production_compose exec -T redis redis-cli --scan --pattern '*:v2:tenant:*:active-admin' \
         | python3 -c 'import base64, sys
       for line in sys.stdin:
           part = line.strip().split(":")[-2]
           print(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)).decode())' | sort -u

   The check stops, creating nothing, if a tester account still has a live
   conversation from an earlier run. Each operator has at most one live
   conversation (#473), so the test accounts cannot end anyone else's.
2. **Storage mode.** In each tenant's SSF configuration in Studio, note the
   conversation-content storage mode (`ask` or `disabled`). Pass it as
   `SSF_RC_TENANT_{A,B}_STORAGE`.
3. **Tester accounts.** In the Keycloak admin console
   (`https://auth.dialog.kassel.de/`), create two users in each tenant's realm,
   named `ssf-release-check-<yyyymmdd>-<n>`. Studio's user management cannot
   do this: it makes the email address the username and sets a password only
   through an emailed link. For each user:
   - fill in email, first and last name and turn on *Email verified*, so the
     realm's user profile asks for nothing at the first login;
   - under *Credentials*, set a password with *Temporary* off;
   - leave *Required user actions* empty. They need no SSF role.
4. Keep the passwords out of the shell history and out of the repository, for
   example in a mode-0600 env file outside the checkout that you source.

## Run

From the repository root, with the development environment installed:

    export SSF_RC_API_BASE=https://ssf.smart-village.solutions
    export SSF_RC_KEYCLOAK_BASE=https://auth.dialog.kassel.de
    export SSF_RC_FRONTEND_ORIGIN=https://dialog.kassel.de
    export SSF_RC_TENANT_A_ID=tenant-kassel SSF_RC_TENANT_A_LANGUAGE=en SSF_RC_TENANT_A_STORAGE=ask
    export SSF_RC_TENANT_B_ID=smart-city-labor SSF_RC_TENANT_B_LANGUAGE=tr SSF_RC_TENANT_B_STORAGE=ask
    export SSF_RC_TENANT_A_USER_1=… SSF_RC_TENANT_A_PASSWORD_1=…   # and _2, and tenant B
    export SSF_RC_REPORT=release-check-report.json                 # optional
    export SSF_RC_MANIFEST=release-check-manifest.json             # for the audio check below
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
| `A1 has no live conversation` … `B2 has no live conversation` | no earlier run left a tester conversation live, so this run cannot end one mid-way |
| `A1 create session` … `guest message 2 delivered` | one full conversation; each message reaches the other participant over WebSocket |
| `A1 audio retrievable during conversation` | every message's recording can be fetched while the conversation runs |
| `A1 → B1 … is not found` | a foreign tenant's session looks exactly like a missing one |
| `A1 → A2 … is not found`, `B1 → B2 … is not found` | a colleague's session in the same tenant looks exactly like a missing one (#476) |
| `… selector … is rejected` | a request cannot choose its tenant |
| `A1 keeps 4 messages`, `A2 keeps 0 messages` | consent-gated retention of the conversation text after termination |
| `A1 serves no audio after termination` | an ended conversation serves no recording to anyone, kept or not |
| `… cleanup` | only when a conversation had not been terminated yet |

## Retained audio (on the production host)

An ended conversation serves no audio through the API, so whether recordings
were kept is checked on disk. `SSF_RC_MANIFEST` holds each test conversation's
session id; copy it to the production host, then from the repository root
there:

    source scripts/lib/production-common.sh
    for row in $(jq -r '.conversations[] | "\(.label):\(.consent):\(.storage):\(.session_id)"' release-check-manifest.json); do
      sid=${row##*:}
      count=$(production_compose exec -T api_gateway sh -c "find /data/audio/v2 -path '*/$sid/translated/*.wav' -type f | wc -l")
      echo "${row%:*} -> $count recordings"
    done

Expected: 4 for a conversation with consent `true` and storage `ask`, 0 for
every other. Then delete the manifest on both machines; the ids it holds
belong to ended conversations but are not needed any more.

## After the run

Delete the four `ssf-release-check-<yyyymmdd>-<n>` users in the Keycloak admin
console, and confirm they no longer appear in either realm. Delete the env file
that held their passwords.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `A1 has no live conversation` fails | a tester conversation from an earlier run is still live; end it or wait for its timeout |
| `A1 → A2 … is not found` fails | the gateway lets a colleague into another admin's session; it predates #476 or lost the owner check |
| `A1 guest reads pending session` fails with 404 for one operator per tenant | the gateway predates #473 and allows one live conversation per tenant, so the second operator's session ended the first; deploy `main` 2383a2a or later |
| `Keycloak requires an action from this user` | the user has a temporary password or another required action |
| `Keycloak rejected the credentials` | wrong password, or the user is in the other tenant |
| `… socket acknowledged` fails with `rejected` | the WebSocket origin is not allowed; `SSF_RC_FRONTEND_ORIGIN` must be the production frontend |
| `… message … delivered` fails, or HTTP 503 on send | translation or TTS is down; check `/health` |
| `A1 keeps 0 messages … is the tenant's storage mode really ask?` | the tenant's storage mode is `disabled`; re-run with the right `…_STORAGE` |
