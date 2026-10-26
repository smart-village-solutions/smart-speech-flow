# Recording Keys Deployment Runbook

## Scope

This runbook brings the first part of recording mode (#614) into production:
the `ssf_recording` database, the gateway's two recording secrets, personal key
enrolment for staff, and step-up MFA in the tenant realms. Nothing is recorded
yet; that arrives with #615.

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

```bash
sudo scripts/recording/generate-secrets.sh /etc/ssf/recording-secrets
```

Expected: `generate-secrets.sh: wrote /etc/ssf/recording-secrets/signing-key.pem
and /etc/ssf/recording-secrets/blob-key`. The script refuses to overwrite
either file.

The gateway runs as the image's `app` user, so it must be able to read them:

```bash
production_compose run --rm --no-deps --entrypoint id api_gateway
# uid=100(app) gid=101(app) ...  -- use the numbers this prints
sudo chown -R 100:101 /etc/ssf/recording-secrets
sudo chmod 0500 /etc/ssf/recording-secrets
sudo chmod 0400 /etc/ssf/recording-secrets/*
```

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
SSF_RECORDING_STEP_UP_ACR=mfa
SSF_RECORDING_STEP_UP_MAX_AGE_SECONDS=300
```

## Step 3 — Create the database on the existing volume

The init scripts run only on a fresh volume, so `apply.sh` is run by hand. First
take the same safety dump as for any migration:

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
with a second factor. The gateway accepts a token whose `acr` is
`SSF_RECORDING_STEP_UP_ACR` (`mfa`) and whose `auth_time` is at most
`SSF_RECORDING_STEP_UP_MAX_AGE_SECONDS` old. Each tenant realm must therefore map
`mfa` to a level of authentication that demands OTP.

Tenant realms are provisioned by Studio, so this configuration belongs in
Studio's realm provisioning (#612). Until it is there, apply it by hand in the
Keycloak admin console of each realm:

1. **Realm settings → General → ACR to LoA Mapping:** add `pwd` → `1` and
   `mfa` → `2`. Save.
2. **Authentication → Flows → browser → Action → Duplicate**, named
   `ssf step-up browser`.
3. In its `forms` sub-flow, delete the existing `Username Password Form` and
   `Conditional OTP` steps, then add:
   - a sub-flow `1st condition`, requirement **Conditional**, containing
     `Condition - Level of Authentication` (Required; level `1`, max age
     `36000`) and `Username Password Form` (Required);
   - a sub-flow `2nd condition`, requirement **Conditional**, containing
     `Condition - Level of Authentication` (Required; level `2`, max age `0`)
     and `OTP Form` (Required).
4. **Action → Bind flow → Browser flow.**
5. **Clients → ssf-frontend → Advanced → Default ACR Values:** `pwd`, so an
   ordinary sign-in stays at level 1.
6. Staff who will hold keys need OTP set up: **Users → (user) → Required user
   actions → Configure OTP**, or they set it up at their next step-up.

Verify with a staff account that holds an `ssf.recording.*` permission:

1. Open the tenant login page, then **user menu → Archivschlüssel**.
2. **Erneut anmelden** must ask for the password and the OTP code, then return
   to the same screen.
3. Create keys with a strong passphrase. The screen shows a fingerprint of ten
   groups of four characters.
4. Sign out, sign in, open the keys screen again, and unlock with the
   passphrase. The fingerprint must match.

## Rollback

Unset `SSF_RECORDING_APP_PASSWORD` in `.env` and run
`production_compose up -d api_gateway`. The recording routes answer 503 again.
The database and its rows stay. Drop them only while nothing has been
archived: `DROP DATABASE ssf_recording` as the owner, then
`DROP ROLE ssf_recording_app`.

## Backups

`backup-production.sh` does not dump `ssf_recording` yet. Its own dump with a
14-day retention arrives with #618, and it must exist before #615 archives
anything. Until then the database holds only key enrolments and their audit
trail; if it is lost, staff enrol again.

## Known limits

- One gateway process. Several workers would each need the secrets, and later
  a shared conversation-key holder (spec §8.1).
- Rotating the blob key is not supported yet. The envelope's leading version
  byte is reserved for it.
- Rotating the signing key: write a new `signing-key.pem` (move the old one
  aside first; the script refuses to overwrite) and restart the gateway. It
  registers the new key ID; old public keys stay in `gateway_signing_keys`, so
  old signatures remain verifiable.
