# Feedback Database Deployment Runbook

## Scope

This runbook brings the feedback store (#301) into production from nothing. It
covers the PostgreSQL service `ssf-postgres`, its two application roles, the six
required secrets, the ClickHouse migration the analytics half depends on, and
the checks that prove each step worked.

Follow it top to bottom. Every step states what to expect, so a step that
produces different output should stop the deployment rather than be repeated.

**Complete this runbook in the same deployment window that ships the compose
file.** All six variables below are declared `:?required`, and Compose
interpolates the whole file before running any command, so until `.env` has all
six, *every* `production_compose` command fails — `up`, `ps`, `logs`, the
systemd backup timers and `production-health-check.sh` alike. That is a
deliberate trade: a mistyped variable stops the deployment instead of producing
a silently broken one. It does mean the host is not in a usable state between
receiving this compose file and finishing Step 1.

Once the variables are set, the rest is unhurried. The gateway starts without
waiting for the database, retries the connection in the background, and answers
`POST /api/feedback` with a retryable 503 until it connects. Conversations are
unaffected throughout: a feedback database that is missing, slow or broken must
never cost a customer their session.

## Security boundary

`ssf-postgres` is the only store that holds feedback free text in a recoverable
form. It is reachable only on the Compose network, has no host port and no
Traefik route, and must never gain either. The text is encrypted at rest with
AES-GCM whose additional authenticated data binds each value to its own feedback
id and tenant, so a row moved to another tenant or another id fails to decrypt
rather than decrypting into the wrong context.

Four database identities exist, and the separation is the security control, not
a convention:

| Role | Privileges | Used by |
| --- | --- | --- |
| owner (`SSF_POSTGRES_USER`) | superuser | migrations and backups only |
| `ssf_feedback_app` | `SELECT, INSERT, UPDATE` on `feedback`, one tenant at a time | `POST /api/feedback` |
| `ssf_feedback_maintenance` | `SELECT, UPDATE, DELETE`, all tenants | reconciliation and retention |
| `ssf_feedback_reader` | `SELECT` on `feedback` and `INSERT` on `feedback_access_audit`, one tenant at a time | the Studio read endpoints |

The request path deliberately has no `DELETE`, so retention cannot be triggered
from an HTTP request. The owner is a superuser and therefore bypasses row-level
security entirely: **never point `SSF_FEEDBACK_DATABASE_URL` at it.** Doing so
silently disables tenant isolation, which is exactly the defect migration 002
exists to prevent.

`ssf_feedback_reader` exists because neither of the other two can serve Studio's
reads. Reusing `ssf_feedback_app` would give the unauthenticated submit path the
ability to write audit rows; reusing `ssf_feedback_maintenance` would read with
`BYPASSRLS`, leaving tenant isolation enforced only by a `WHERE` clause in
Python. The read role is `NOBYPASSRLS` like the request path, so migration 001's
policy filters every read: an operator signed in to one tenant cannot be served
another tenant's feedback even if the query forgets to ask. It holds no `UPDATE`
and no `DELETE` — withdrawal is not part of this path (see Known limits).

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

Seven values are required. All are declared `:?required`, so the stack refuses
to start without them rather than starting in a broken state.

Generate the four new ones on the production host and write them straight into
the untracked production `.env`:

```bash
# Three role passwords and the database owner's password.
for name in SSF_POSTGRES_PASSWORD SSF_FEEDBACK_APP_PASSWORD SSF_FEEDBACK_MAINTENANCE_PASSWORD SSF_FEEDBACK_READER_PASSWORD; do
  printf '%s=%s\n' "$name" "$(openssl rand -base64 32)" >> .env
done

# The encryption key: exactly 32 bytes, base64-encoded.
printf 'SSF_FEEDBACK_ENCRYPTION_KEY=%s\n' "$(openssl rand -base64 32)" >> .env

# Identifiers, not secrets.
printf 'SSF_POSTGRES_DB=ssf\nSSF_POSTGRES_USER=ssf\nSSF_DEFAULT_TENANT_ID=default\n' >> .env
```

`deploy/production/production.env.example` documents all of them with the same
names.

Any output these generators produce is safe to use. The role passwords reach
PostgreSQL as psql variables and reach the gateway in their own environment
variables, never inside a connection URL — `/` and `@` in a URL password break
asyncpg, one loudly and one silently.

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

Wait for the health check to report healthy. It probes over TCP
(`pg_isready -h 127.0.0.1`) rather than the unix socket, because during the
first start the image runs a temporary socket-only server while the migrations
execute — a socket probe reports healthy before the roles exist.

Then confirm both migrations ran:

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

Expect exactly four rows:

```
ssf|t|t
ssf_feedback_app|f|f
ssf_feedback_maintenance|f|t
ssf_feedback_reader|f|f
```

`ssf_feedback_app` and `ssf_feedback_reader` must both show `f|f`. If either
shows `t` in either column, that path can read every tenant's feedback and the
deployment must stop here. `ssf_feedback_reader` showing `f|t` is the specific
failure that makes the Studio endpoints serve one tenant's feedback to another,
and nothing else will report it.

Confirm the request role cannot delete, and that the read role can neither
delete nor update:

```bash
production_compose exec -T ssf-postgres sh -ec \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
   "SELECT has_table_privilege('"'"'ssf_feedback_app'"'"', '"'"'feedback'"'"', '"'"'DELETE'"'"')
    UNION ALL
    SELECT has_table_privilege('"'"'ssf_feedback_reader'"'"', '"'"'feedback'"'"', '"'"'DELETE'"'"')
    UNION ALL
    SELECT has_table_privilege('"'"'ssf_feedback_reader'"'"', '"'"'feedback'"'"', '"'"'UPDATE'"'"')"'
```

Expect `f` three times.

## Step 4 — Restart the gateway

The gateway reads both connection strings and both passwords at startup. They
are assembled in the compose file from the values set in Step 1, so nothing
further is needed:

```bash
production_compose up -d api_gateway
production_compose logs api_gateway | grep -i feedback
```

Expect both of these:

```
Feedback persistence ready
Feedback maintenance ready
```

They are reported separately because the two halves connect, fail and recover
independently: either line can appear without the other.

The gateway does not wait for the database to be healthy — a failed migration
must not stop the service that carries every conversation — so on a first
deploy it usually starts before the database is listening and connects on a
later retry. A line reporting one half unavailable is therefore normal for the
first minute or so, and the matching `ready` line should follow within about
that long.

Lines that mean something is actually wrong:

- `Feedback persistence unavailable (<ErrorType>)` repeating past a couple of
  minutes — the database is refusing the connection. The type name is
  deliberate: a connection error carries the DSN, and the DSN carries the
  password, so the message never includes either. `InvalidPasswordError` means
  Step 1 and Step 2 disagree about a password, usually because the volume
  predates the current `.env`.
- `Feedback maintenance unavailable (<ErrorType>)` on its own — submissions are
  being stored, but neither analytics recovery nor twelve-month deletion is
  running. Reported separately from the line above precisely because the two
  fail independently.
- `Feedback persistence disabled: SSF_FEEDBACK_ENCRYPTION_KEY is missing or
  malformed` — the key failed to decode to 32 bytes. The gateway keeps serving
  conversations and answers every submission with a 503; it does not retry,
  because a key does not appear on its own.

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
`ssf_feedback_reconciliation_backlog`, `ssf_feedback_retention_deleted_total`,
`ssf_feedback_retention_overdue` and `ssf_feedback_maintenance_failures_total`.
Both gauges should sit at or near zero.

Five alert rules cover these and load with the Prometheus configuration:
`FeedbackReconciliationBacklogGrowing`, `FeedbackReconciliationFailing`,
`FeedbackRetentionNotRunning`, `FeedbackRetentionDeletingNothing` and
`FeedbackMaintenanceJobFailing`.

The two retention rules catch different failures, and neither catches the
other's. `FeedbackRetentionNotRunning` fires on the *absence* of the counter,
because a pass that never runs produces no failures to count.
`FeedbackRetentionDeletingNothing` fires when rows are past expiry and nothing
has been deleted for six hours — the case where the pass runs, reports success
and removes nothing, which is what a maintenance role that lost `BYPASSRLS`
does on every cycle.

Note the reconciliation backlog gauge reports the claimed batch, capped at the
batch limit of 200, so a larger backlog reads as exactly 200 until it drains
below that. The alert only tests the threshold, so it still fires.

## Step 8 — Read the numbers

The **SSF Telemetry** dashboard in Grafana's SSF folder carries the feedback
KPIs: submissions, response rate, NPS with its promoter/passive/detractor
split, the three rating averages, and a per-form-version table that shows the
denominator beside each average.

Two panels need reading carefully, and both say so in their own descriptions:

- **Rating Averages** is exact but reads the silver tier, which keeps 30 days.
  A longer time range truncates silently.
- **Rating Averages (Gold Tier, approximate)** covers thirteen months and is
  approximate by construction: `avgState` has no distinct-by form, so a
  submission re-emitted by the reconciler contributes its ratings twice.
  Measured against ClickHouse 26.3.17 with one re-emission, gold reported 3.5
  where the true average was 3.0. Counts and NPS are built on `uniqExact` and
  stay exact in both tiers.

If the panels are empty after a real submission, check Step 5 first: without
ClickHouse migration `005` the feedback columns do not exist, and the events
land carrying only their envelope.

## Step 9 — Verify the Studio read endpoints

Two authenticated endpoints let Studio read what was submitted:

| Endpoint | Returns |
| --- | --- |
| `GET /api/feedback` | one page of the caller's tenant: ratings, dates, form version, analytics state, and `has_improvements` — never the text itself |
| `GET /api/feedback/{feedback_id}` | one record including its decrypted free text |

Both take the tenant from the signed `studio_tenant_id` claim in the bearer
token. A tenant supplied by the request — query string, header, cookie or body
— is rejected with `400`, so an operator cannot widen their own scope. A record
belonging to another tenant answers `404`, identical to one that does not
exist, so the endpoint cannot be used to discover which ids are real elsewhere.

Confirm the gateway wired the read role:

```bash
production_compose logs api_gateway | grep -i "feedback reading"
```

Expect `Feedback reading ready`. `Feedback reading disabled:
SSF_FEEDBACK_READER_DATABASE_URL is not set` means the endpoints will answer
`503` while submissions keep working — correct for a deployment that has not
granted Studio read access, and a misconfiguration for one that has.

Every read writes a row to `feedback_access_audit`, with `access_scope` of
`list` or `detail`. Reading a record is an audited disclosure; confirm the audit
is actually being written before relying on it:

```bash
production_compose exec -T ssf-postgres sh -ec \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
   "SELECT access_scope, count(*) FROM feedback_access_audit GROUP BY access_scope"'
```

A refused read writes nothing: nothing was disclosed, and an audit row for an
id the caller cannot read would let anyone fill the table with ids they guessed.

## Backups

`scripts/backup-production.sh` already includes `ssf-postgres.sql.gz` and runs
`pg_dump` as the owner. No change is needed, but verify the dump appears after
the first scheduled run. A backup is a directory with a `latest` symlink beside
it, not an archive:

```bash
ls -l backups/daily/latest/ssf-postgres.sql.gz
```

If the file is absent, check the backup's stderr for
`ssf-postgres is not running`. The script skips this one dump when the service
is not up, rather than aborting and taking the Keycloak, Redis and ClickHouse
backups down with it — but a skip on a host where the service *should* be
running means twelve months of feedback is going unbacked-up.

The dump is only half of what a restore needs: **the encryption key is the
other half**, and a backup taken without it restores unreadable rows.

## Rollback

The feedback store is additive: nothing else reads it, and no other service
changes behaviour when it stops. Rolling back means taking the database out of
service, not undoing a migration.

`SSF_FEEDBACK_DATABASE_URL` is assembled in the tracked compose file, so it
cannot be unset from `.env` and must not be edited on the host. Stop the
database instead:

```bash
# Submissions answer a retryable 503; conversations are unaffected.
production_compose stop ssf-postgres
```

The gateway keeps running, retries in the background, and reconnects by itself
when the database comes back — no gateway restart is needed in either
direction. Leave the variables in `.env`: removing them breaks every
`production_compose` command on the host, including the backups for every other
service.

Leave the volume in place. Removing the volume destroys every
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

**Stopping submissions without stopping retention.** Unsetting
`SSF_FEEDBACK_DATABASE_URL` turns off `POST /api/feedback` and leaves both
background passes running, so rows already stored are still deleted at their
twelve-month expiry. The two halves are wired independently on purpose: the
notice promises that deletion in ten languages, and no code path should be able
to stop enforcing it as a side effect of switching submission off.

**Retention never deletes anything.** Expected on a deployment younger than
twelve months — nothing has expired yet. `ssf_feedback_retention_deleted_total`
exists and stays at zero; the pass is running.

**Two replicas and a pass seems to skip.** By design, and true of both passes.
Each takes an advisory lock so only one replica works per cycle; the others
record a skip, which is not a failure and is not counted as one. Without it the
reconciler would re-emit every pending row once per replica, and while
ClickHouse deduplicates the counts on `event_id`, the rating averages would
skew by a factor scaling with replica count.

**`permission denied for table feedback`.** Something is connecting as the wrong
role. Check which DSN the failing path uses; the request path and the background
passes are not interchangeable.

## Known limits

These are properties of the design, not defects to report:

- **Reading is an API, not a UI.** `GET /api/feedback` and
  `GET /api/feedback/{feedback_id}` serve Studio (Step 9), and every read is
  audited. There is still no feedback-review page in SSF itself — a browsing
  surface was explicitly out of scope for #301 — so an operator without Studio
  reads these through an authenticated HTTP client or not at all.
- **Rating averages are not retry-safe.** ClickHouse `avgState` has no
  distinct-by form, so a re-emitted submission contributes twice to the gold
  table's rating averages. Counts and rates stay exact. Read averages from
  silver's thirty days when exactness matters.
- **`delivered` means accepted, not received.** The analytics event is marked
  delivered once the OTLP batch processor takes it; the export happens later on
  a worker thread and its result never returns. During a Collector outage rows
  are marked delivered and the events are lost, so the reconciler sees no
  backlog — the one outage it was built for is the one it cannot detect. Watch
  `QualityTelemetryCollectorDown` for that case instead.
- **Backups outlive the retention promise.** Feedback is deleted from the
  database at twelve months, but monthly backups are kept for twelve more, so a
  deleted submission can persist in backup storage for up to about twenty-four
  months. Restoring an old backup restores deleted feedback; the next retention
  pass removes it again within the hour. If the twelve-month figure in the
  submission notice has to hold for backups too, the backup retention needs
  shortening — that is a decision for the privacy owner, not a code change.
- **Feedback cannot be withdrawn on request.** The submission notice offers a
  withdrawal route through staff, and no procedure implements it: there is no
  lookup by person or session, and `feedback_deletion_audit.reason` only ever
  records `retention_expiry`. Deletion happens on the twelve-month schedule
  alone. A GDPR erasure request arriving before then cannot currently be
  served.
- **The endpoint is open.** Submission needs no authentication, by the same
  design as the rest of the customer flow, and is bounded only by the global
  per-client rate limit. Anyone who can reach the gateway can add rows that are
  kept for a year.
- **Submission is single-tenant; reading is not.** The two halves are at
  different stages on purpose, and the difference matters operationally.

  The read endpoints are genuinely multi-tenant today: the tenant comes from a
  signed claim, `ssf_feedback_reader` is `NOBYPASSRLS`, and PostgreSQL's own
  policy filters every read (Step 3 verifies this).

  Submission is not. `POST /api/feedback` is unauthenticated by design — the
  customer flow carries no Keycloak identity — so its tenant cannot come from a
  token. It would have to come from the session, and sessions do not carry a
  tenant yet: `SSF_DEFAULT_TENANT_ID` supplies one value for the whole
  deployment. **Every submission from every tenant is therefore stored under
  that single configured tenant, and the read endpoints will show all of it to
  any tenant's operator.**

  Tenant-binding sessions is issue #288, which is gated behind #299 in the
  delivery order recorded on #266. Until it lands:

  - A deployment serving one live tenant is unaffected in practice.
  - A deployment serving more than one must not treat the read endpoints as a
    tenant boundary for submitted feedback, because the rows behind them are
    commingled at write time.
  - Feedback collected before #288 stays attributed to the configured tenant.
    Re-attributing it afterwards is an `UPDATE` on `tenant_id`, not a
    migration — the column and the policy are already in place — but it needs
    someone to decide which rows belonged to whom, which is only answerable
    while one tenant is live.

  The order to deploy in follows from that: land #288 before a second tenant
  begins collecting feedback, not after.
