# Recording Keys Deployment Runbook

## Scope

This runbook brings the first part of recording mode (#614) into production:
the `ssf_recording` database, the gateway's two recording secrets, personal key
enrolment for staff, step-up MFA in the tenant realms, and each tenant's
recovery-key ceremony. Nothing is recorded yet; that arrives with #615.

Everything here is optional per host. Until `SSF_RECORDING_APP_PASSWORD` is set
and the secrets directory holds both files, the gateway serves conversations as
before and every `/api/admin/recording/*` route answers 503
`RECORDING_UNAVAILABLE`. No variable below is `:?required`, so receiving the
compose file does not break any `production_compose` command.

Follow the steps top to bottom. Each one says what to expect; output that
differs should stop the rollout rather than be repeated.

## Every command targets the production stack

```bash
source scripts/lib/production-common.sh
```

`production_compose` is `docker compose --project-name ssf-backend --env-file
.env --file deploy/production/docker-compose.production.yml`.

## Step 1 — Generate the gateway secrets

The signing key signs key wraps, chain entries and ceremony transcripts. The
blob key is the server layer around every stored private-key blob, so that a
database dump alone gives an attacker nothing to test passphrase guesses
against. Both live outside `.env`, because `backup-production.sh` copies `.env`
into every backup.

The gateway runs as the image's `app` user, so the files are written for it.
Find its numbers first:

```bash
production_compose run --rm --no-deps --entrypoint id api_gateway
# uid=100(app) gid=101(app) ...  -- use the numbers this prints
sudo scripts/recording/generate-secrets.sh /etc/ssf/recording-secrets 100:101
```

Expected: `generate-secrets.sh: wrote /etc/ssf/recording-secrets/signing-key.pem
and /etc/ssf/recording-secrets/blob-key for 100:101`. The directory is then
0500 and both files 0400, owned by that user. The script refuses to overwrite
either file.

**Back the directory up offline now**, for example to an encrypted USB key kept
by the operator. It is deliberately in no backup the host makes. Losing the blob
key makes every enrolled private key unreadable, and every user must enrol
again. Once #615 is live, losing the signing key means signatures can no longer
be made with it, though old ones stay verifiable.

## Step 2 — Configure `.env`

```bash
openssl rand -base64 32   # the role password
```

Add:

```
SSF_RECORDING_APP_PASSWORD=<the password above>
SSF_RECORDING_SECRETS_DIR=/etc/ssf/recording-secrets
```

## Step 3 — Create the database on the existing volume

The init scripts run only on a fresh volume, so `apply.sh` is run by hand. First
take the same safety dump as for any migration. It holds the feedback database,
not `ssf_recording`; dumps of `ssf_recording` go to `backups/recording/` only,
where they are pruned at 14 days (recording-retention-deployment.md, Step 7):

```bash
production_compose exec -T ssf-postgres sh -ec \
  'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' | gzip -c > ssf-postgres-before-recording.sql.gz
```

Recreate the database container so that it sees the new password, then apply:

```bash
production_compose up -d ssf-postgres
production_compose exec -T ssf-postgres /docker-entrypoint-initdb.d/apply.sh
```

Recreating the container interrupts feedback submissions for a few seconds;
they answer a retryable 503 meanwhile.

Expected, after the four feedback lines:

```
apply.sh: ensuring database ssf_recording
apply.sh: applying /docker-entrypoint-initdb.d/recording/migrations/001_recording_keys.sql to ssf_recording
apply.sh: applying /docker-entrypoint-initdb.d/recording/migrations/002_recovery_ceremony.sql to ssf_recording
apply.sh: applying /docker-entrypoint-initdb.d/recording/migrations/003_recording_archive.sql to ssf_recording
apply.sh: done
```

## Step 4 — Verify the privilege separation

```bash
production_compose exec -T ssf-postgres sh -ec \
  'psql -U "$POSTGRES_USER" -d ssf_recording -tAc "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = \$\$ssf_recording_app\$\$"'
```

Expected: `f|f`. Then confirm the feedback role
cannot reach the new database:

```bash
production_compose exec -T ssf-postgres sh -ec \
  'PGPASSWORD="$SSF_FEEDBACK_APP_PASSWORD" psql -h 127.0.0.1 -U ssf_feedback_app -d ssf_recording -c "SELECT 1"'
```

Expected: `User does not have CONNECT privilege.`

## Step 5 — Restart the gateway

```bash
production_compose up -d api_gateway
production_compose logs api_gateway | grep -i recording
```

Expected: `Recording keys ready`. `Recording disabled: ...` names the missing
piece: the password, or a secret file the gateway cannot read (Step 1's
ownership). `Recording storage unavailable` means the database is not reachable
yet; the gateway retries on its own with backoff up to 60 s.

## Step 6 — Step-up MFA in each tenant realm

Enrolment, and later the recovery ceremony and approvals, require a fresh login
with a second factor. The gateway accepts a token whose `acr` is `mfa` and
whose `auth_time` is at most 300 seconds old; both values are fixed in the
gateway and the frontend. Each tenant realm must therefore map `mfa` to a
level of authentication that demands OTP.

Studio provisions this in every tenant realm: the levels `pwd` → `1` and
`mfa` → `2`, login flows whose level 2 always asks for the OTP code, and the
`acr` claim in `ssf-frontend` tokens. Its Keycloak provisioning run applies them
together with the tenant's ordinary-login MFA setting, which is optional by
default. Do not configure the realm by hand: Studio refuses to replace a browser
flow it did not create (`LOGIN_MFA_BINDING_CONFLICT`), so the tenant's MFA
setting would never take effect.

1. In Studio, open the tenant's instance. Under **Ordinary login MFA** (**MFA
   bei normaler Anmeldung**) keep **optional**, or choose **required** to ask
   for the code at every sign-in. Step-up asks for it either way.
2. Wait until the instance's Keycloak status shows **Tenant login MFA
   verified**. A pending or failed run means the realm is not ready yet; the
   run's diagnostic names the cause.
3. Staff who will hold keys need OTP set up: **Users → (user) → Required user
   actions → Configure OTP** in Keycloak, or they set it up at their next
   step-up.

**A realm configured by hand** with the earlier version of this step: in its
Keycloak admin console, **Authentication → Flows → browser → Action → Bind flow
→ Browser flow**, then delete the `ssf step-up browser` flow, and save the MFA
setting in Studio again to retry its run. Enrolled OTP codes stay.

Verify with a staff account that holds an `ssf.recording.*` permission:

1. Open the tenant login page, then **user menu → Archivschlüssel**.
2. **Erneut anmelden** must ask for the password and the OTP code, then return
   to the same screen.
3. Create keys with a strong passphrase. The screen shows a fingerprint of ten
   groups of four characters.
4. Sign out, sign in, open the keys screen again, and unlock with the
   passphrase. The fingerprint must match.

## Step 7 — The recovery-key ceremony, per tenant

Each tenant needs a recovery key before #615 can let it record. No device ever
holds that key: custodians each deal a share of it in their own browsers, and
the gateway only relays and checks what they publish (spec §9.2).

**Before the day.**
- Studio must list the custodians: each needs the
  `ssf.recording.recovery.custodian` permission, and Studio's recording
  directory (`/internal/plugins/ssf/v2/recording-directory`) must answer. Check
  with the tenant administrator's **user menu → Wiederherstellungsschlüssel**:
  the custodians appear there.
- Every custodian has enrolled personal keys (Step 6) and knows their
  passphrase. One without keys is listed as "noch keine Archivschlüssel" and
  cannot be chosen.
- Choose `k`, the shares needed to open a conversation. Name at least `k + 1`
  custodians, at most 10, so a recovery can proceed when the requester is a
  custodian. `k = 1` is the standard mode and offers no cryptographic
  separation; `k ≥ 2` is the enhanced mode.
- For a paper backup, prepare a dedicated ceremony device that no custodian
  uses, with a printer attached. The tenant administrator signs in on it.
  The paper backup is `k` sheets, each given to a different person.

**The ceremony.** Everyone meets in person or by video. It must finish within
24 hours of its start, or it lapses.
1. The tenant administrator, on the ceremony device, opens
   **Wiederherstellungsschlüssel**, signs in again with the second factor,
   chooses the custodians, `k`, and whether to print a paper backup, and
   starts the ceremony. That device must stay open until the sheets are
   printed: a reload loses its key, and the ceremony must then be aborted and
   started again.
2. Each custodian opens the same screen, unlocks their archive keys, and reads
   every fingerprint aloud. Each person compares their own fingerprint with the
   one shown for them on every other screen, and the device fingerprint shown
   on the ceremony device. On any difference, abort.
3. Each custodian ticks the comparison box and selects **Beitrag abgeben**.
4. When everyone has dealt, each custodian selects **Prüfen und
   unterschreiben**. Their browser checks every dealing, and aborts the
   ceremony itself if anything fails.
5. On the ceremony device: **Prüfen und Papieranteile erzeugen**, **Drucken**,
   seal each sheet separately and hand it to its holder, tick the box, and
   select **Papiersicherung abschließen**.
6. The screen shows "Der Wiederherstellungsschlüssel ist aktiv" with `k` of `n`.
   Note the transcript value it shows in the tenant's records.

Check the audit trail:

```bash
production_compose exec -T ssf-postgres sh -ec \
  'psql -U "$POSTGRES_USER" -d ssf_recording -tAc "SELECT tenant_id, status, k, n FROM recovery_keys"'
```

Expected: one `active` row for the tenant.

## Step 8 — The mail relay for re-enrolment links (#632)

A user who forgot their passphrase sets up a new key, but it becomes active
only once they open a one-time link mailed to the address stored with their
current key (spec §9.9). Without a relay, re-enrolment answers 503
`MAIL_UNAVAILABLE`; first enrolment, which stores the address, needs no mail.

**Before you start.**
- The relay must offer TLS with a certificate a standard client trusts. The
  gateway always verifies it; there is no setting to turn that off.
- `CLIENT_BASE_URL` (already `https://dialog.kassel.de` in the compose file) is
  where the link points.
- Each tenant realm's access token must carry `email` and `email_verified`.
  Keycloak's default `email` client scope adds both; check once by enrolling a
  test user (Step 6). Enrolment answers 409 `EMAIL_NOT_VERIFIED` otherwise.

**The password file**, readable by the gateway's user (Step 1's numbers):

```bash
sudo install -m 0400 -o 100 -g 101 /dev/stdin /etc/ssf/recording-secrets/smtp-password
# paste the relay password, then Ctrl-D
```

**`.env`:**

```
SSF_SMTP_HOST=<relay host>
SSF_SMTP_PORT=587
SSF_SMTP_SECURITY=starttls
SSF_SMTP_FROM=KasselDIALOG <noreply@dialog.kassel.de>
SSF_SMTP_USERNAME=<relay user>
SSF_SMTP_PASSWORD_FILE=/run/secrets/ssf-recording/smtp-password
```

`SSF_SMTP_SECURITY` is `starttls` (port 587) or `tls` (port 465). `none` is
refused in production. Username and password file go together or not at all.

```bash
production_compose up -d api_gateway
production_compose logs api_gateway | grep -i "re-enrolment mail"
```

Expected: no line. `Re-enrolment mail disabled: ...` names the missing or
refused setting, never its value. Then re-enrol a test user from the keys
screen: the mail arrives in German and English, and its link opens the
confirm page without a login. A failed send logs `Re-enrolment mail failed:
<error type>` and the user sees "cannot be sent right now".

## Rollback

Unset `SSF_RECORDING_APP_PASSWORD` in `.env` and run
`production_compose up -d api_gateway`. The recording routes answer 503 again.
The database and its rows stay. Drop them only while nothing has been
archived: `DROP DATABASE ssf_recording` as the owner, then
`DROP ROLE ssf_recording_app`.

## Backups

`backup-production.sh` never dumps `ssf_recording`: its tiers keep copies for
up to twelve months, longer than a shredded conversation may survive in any
backup. `scripts/backup-recording.sh` dumps it daily into `backups/recording/`
and deletes dumps older than 14 days (recording-retention-deployment.md,
Step 7). It must run before anything is archived.

## Known limits

- One gateway process. Several workers would each need the secrets, and later
  a shared conversation-key holder (spec §8.1).
- Rotating the blob key is not supported yet. The envelope's leading version
  byte is reserved for it.
- Rotating the signing key: write a new `signing-key.pem` (move the old one
  aside first; the script refuses to overwrite) and restart the gateway. It
  registers the new key ID; old public keys stay in `gateway_signing_keys`, so
  old signatures remain verifiable.
