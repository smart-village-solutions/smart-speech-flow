# Feedback Database Deployment Runbook

## Scope

This runbook brings the feedback store (#301) into production from nothing. It
covers the PostgreSQL service `ssf-postgres`, its two application roles, the six
required secrets, the ClickHouse migration the analytics half depends on, and
the checks that prove each step worked.

Follow it top to bottom. Every step states what to expect, so a step that
produces different output should stop the deployment rather than be repeated.

**Until this runbook is completed, `POST /api/feedback` answers a retryable 503
and nothing else is affected.** The gateway logs `Feedback persistence disabled`
at startup and serves conversations normally. There is no rush and no partial
state to clean up: deploy this when it suits, not during an incident.

## Security boundary

`ssf-postgres` is the only store that holds feedback free text in a recoverable
form. It is reachable only on the Compose network, has no host port and no
Traefik route, and must never gain either. The text is encrypted at rest with
AES-GCM whose additional authenticated data binds each value to its own feedback
id and tenant, so a row moved to another tenant or another id fails to decrypt
rather than decrypting into the wrong context.

Three database identities exist, and the separation is the security control, not
a convention:

| Role | Privileges | Used by |
| --- | --- | --- |
| owner (`SSF_POSTGRES_USER`) | superuser | migrations and backups only |
| `ssf_feedback_app` | `SELECT, INSERT, UPDATE` on `feedback`, one tenant at a time | `POST /api/feedback` |
| `ssf_feedback_maintenance` | `SELECT, UPDATE, DELETE`, all tenants | reconciliation and retention |

The request path deliberately has no `DELETE`, so retention cannot be triggered
from an HTTP request. The owner is a superuser and therefore bypasses row-level
security entirely: **never point `SSF_FEEDBACK_DATABASE_URL` at it.** Doing so
silently disables tenant isolation, which is exactly the defect migration 002
exists to prevent.

## Every command targets the production stack

A bare `docker compose` from the repository root reads `docker-compose.yml` plus
any local override, under a project name derived from the directory — a
different stack from the one production runs. Source the helper first:

```bash
source scripts/lib/production-common.sh
```

`production_compose` is `docker compose --project-name ssf-backend --env-file
.env --file deploy/production/docker-compose.production.yml`; spell that out in
full if you would rather not source the helper.

## Step 1 — Generate the secrets

Six values are required. All are declared `:?required`, so the stack refuses to
start without them rather than starting in a broken state.

Generate the three new ones on the production host and write them straight into
the untracked production `.env`:

```bash
# Two role passwords and the database owner's password.
for name in SSF_POSTGRES_PASSWORD SSF_FEEDBACK_APP_PASSWORD SSF_FEEDBACK_MAINTENANCE_PASSWORD; do
  printf '%s=%s\n' "$name" "$(openssl rand -base64 32)" >> .env
done

# The encryption key: exactly 32 bytes, base64-encoded.
printf 'SSF_FEEDBACK_ENCRYPTION_KEY=%s\n' "$(openssl rand -base64 32)" >> .env

# Identifiers, not secrets.
printf 'SSF_POSTGRES_DB=ssf\nSSF_POSTGRES_USER=ssf\nSSF_DEFAULT_TENANT_ID=default\n' >> .env
```

`deploy/production/production.env.example` documents all of them with the same
names.

### The encryption key has no recovery path

This is the one irreversible decision in this runbook. The key is never derived
and never defaulted: a generated-on-the-fly key would encrypt rows nobody could
read afterwards, so the gateway refuses to start without one.

**If the key is lost or rotated, every row written under the previous key
becomes permanently unreadable.** There is no recovery, no re-encryption path
and no escrow. Back it up wherever this deployment keeps its other irreplaceable
secrets, before continuing. Confirm the backup exists before Step 2 — after the
first submission is stored, losing the key means losing that data.

Verify the key is well-formed before starting anything:

```bash
# Expect: 32
grep '^SSF_FEEDBACK_ENCRYPTION_KEY=' .env | cut -d= -f2- | base64 -d | wc -c
```

## Step 2 — Start the database

The first start creates the volume and runs every migration in
`deploy/postgres/migrations/` in filename order, through
`/docker-entrypoint-initdb.d/apply.sh`:

```bash
production_compose up -d ssf-postgres
production_compose ps ssf-postgres
```

Wait for the health check to report healthy, then confirm both migrations ran:

```bash
production_compose logs ssf-postgres | grep 'apply.sh'
```

Expect exactly this, in this order:

```
apply.sh: applying /docker-entrypoint-initdb.d/migrations/001_feedback.sql to ssf
apply.sh: applying /docker-entrypoint-initdb.d/migrations/002_feedback_roles.sql to ssf
apply.sh: done
```

If `002` is missing, the roles do not exist and Step 4 will fail to
authenticate. Do not work around it by connecting as the owner.

## Step 3 — Verify the privilege separation

This is the check that proves tenant isolation is real rather than declared. The
credentials are expanded inside the container, so they stay out of the host's
shell history:

```bash
production_compose exec -T ssf-postgres sh -ec \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
   "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname LIKE '"'"'ssf%'"'"' ORDER BY rolname"'
```

Expect exactly three rows:

```
ssf|t|t
ssf_feedback_app|f|f
ssf_feedback_maintenance|f|t
```

`ssf_feedback_app` must show `f|f`. If it shows `t` in either column, the
request path can read every tenant's feedback and the deployment must stop here.

Confirm the request role cannot delete:

```bash
production_compose exec -T ssf-postgres sh -ec \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
   "SELECT has_table_privilege('"'"'ssf_feedback_app'"'"', '"'"'feedback'"'"', '"'"'DELETE'"'"')"'
```

Expect `f`.

## Step 4 — Restart the gateway

The gateway reads both connection strings at startup. They are assembled in the
compose file from the passwords set in Step 1, so nothing further is needed:

```bash
production_compose up -d api_gateway
production_compose logs api_gateway | grep -i feedback
```

Expect `Feedback persistence ready`.

Two other lines are possible and both mean something is wrong:

- `Feedback persistence disabled: SSF_FEEDBACK_DATABASE_URL is not set` — the
  variable did not reach the container. Check the `.env` the helper points at.
- `Feedback persistence unavailable (<ErrorType>)` — the database refused the
  connection. The type name is deliberate: a connection error carries the DSN,
  and the DSN carries the password, so the message never includes either.
  `InvalidPasswordError` means Step 1 and Step 2 disagree about a password,
  usually because the volume predates the current `.env`.

## Step 5 — Apply the ClickHouse migration

The analytics half needs migration `005`, which adds the feedback columns and
the `feedback_daily` aggregate.

**Apply it before setting `SSF_QUALITY_TELEMETRY_MODE=enabled`.** Feedback
events emitted while the columns are missing land with only their envelope
populated, and those rows cannot be repaired afterwards — the attributes never
reached ClickHouse.

Follow the enablement procedure in
[clickhouse-operations.md](clickhouse-operations.md); migration `005` applies the
same way as `002` through `004`.

## Step 6 — Confirm a real submission is stored

Submit one piece of feedback through the UI, then confirm the row exists and the
free text is not readable in the database:

```bash
production_compose exec -T ssf-postgres sh -ec \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
   "SELECT analytics_state, improvements_ciphertext IS NOT NULL, expires_at::date FROM feedback ORDER BY created_at DESC LIMIT 1"'
```

Expect `delivered|t|<today plus twelve months>`, or `not_applicable` in place of
`delivered` while telemetry is still `disabled`. Both are correct.

`pending` means the row was stored but its analytics event did not go out. That
is recoverable rather than lost: the reconciliation pass retries it within five
minutes. If it is still `pending` after fifteen, see Troubleshooting.

The second column must be `t`. The text is encrypted; there is no supported way
to read it back, and no endpoint or admin page exposes it — see Known Limits.

## Step 7 — Confirm the background passes are running

Reconciliation runs every five minutes and retention every hour. Both expose
metrics:

```bash
production_compose exec -T api_gateway curl -s http://localhost:8000/metrics \
  | grep ssf_feedback
```

Expect `ssf_feedback_reconciliation_total`,
`ssf_feedback_reconciliation_backlog`, `ssf_feedback_retention_deleted_total`
and `ssf_feedback_maintenance_failures_total`. The backlog gauge should sit at
or near zero.

Four alert rules cover these and load with the Prometheus configuration:
`FeedbackReconciliationBacklogGrowing`, `FeedbackReconciliationFailing`,
`FeedbackRetentionNotRunning` and `FeedbackMaintenanceJobFailing`.

`FeedbackRetentionNotRunning` fires on the *absence* of the retention counter for
six hours, not on a failure count, because a retention pass that never runs
produces no failures to count.

## Backups

`scripts/backup-production.sh` already includes `ssf-postgres.sql.gz` and runs
`pg_dump` as the owner. No change is needed, but verify the dump appears after
the first scheduled run:

```bash
tar -tzf <latest backup archive> | grep ssf-postgres
```

Without this dump, twelve months of retained feedback has no recovery path. Note
that the dump is only half of what a restore needs: **the encryption key is the
other half**, and a backup taken without it restores unreadable rows.

## Rollback

The feedback store is additive. Nothing else depends on it, so rolling back is
removing it from the gateway's view rather than undoing a migration:

```bash
# Stop accepting submissions; the endpoint returns a retryable 503 again.
# Comment out SSF_FEEDBACK_DATABASE_URL in the gateway environment, then:
production_compose up -d api_gateway
```

Leave `ssf-postgres` and its volume running. Removing the volume destroys every
stored submission, and the twelve-month retention promise made to the people who
submitted them is a commitment to hold the data, not a licence to discard it
early.

## Troubleshooting

**A submission stays `pending` for more than fifteen minutes.** The reconciler
is not draining. Check `ssf_feedback_maintenance_failures_total{job="reconciliation"}`
and the gateway log for `Feedback maintenance pass failed`. The most likely
cause is that `SSF_FEEDBACK_MAINTENANCE_DATABASE_URL` is unset, in which case
the startup log says `Feedback maintenance disabled` and both passes are
skipped while submissions keep working.

**Retention never deletes anything.** Expected on a deployment younger than
twelve months — nothing has expired yet. `ssf_feedback_retention_deleted_total`
exists and stays at zero; the pass is running.

**Two replicas and retention seems to skip.** By design. The pass takes a
transaction-scoped advisory lock so only one replica deletes per cycle; the
others record a skip, which is not a failure and is not counted as one.

**`permission denied for table feedback`.** Something is connecting as the wrong
role. Check which DSN the failing path uses; the request path and the background
passes are not interchangeable.

## Known limits

These are properties of the design, not defects to report:

- **No one can read submitted feedback.** There is no admin page, no `GET`
  endpoint and no dashboard panel — a feedback-review UI was explicitly out of
  scope for #301. The `feedback_access_audit` table is created and deliberately
  unused, waiting for that reader. The ratings are queryable in ClickHouse; the
  free text is reachable only by decrypting it directly with the key.
- **Rating averages are not retry-safe.** ClickHouse `avgState` has no
  distinct-by form, so a re-emitted submission contributes twice to the gold
  table's rating averages. Counts and rates stay exact. Read averages from
  silver's thirty days when exactness matters.
- **All feedback lands under one tenant.** `SSF_DEFAULT_TENANT_ID` supplies it
  until sessions carry a real tenant. The `tenant_id` column and the isolation
  policy are already in place, so that change needs no migration — but feedback
  collected before then stays attributed to the configured tenant.
