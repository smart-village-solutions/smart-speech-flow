# Recording Retention Deployment Runbook

## Scope

This runbook brings retention, legal hold and deletion of recorded
conversations (#618) into production:

- migration 004 and the two worker roles;
- the private link from the gateway host's database to both archive VMs;
- a retention worker on each archive VM;
- the daily 14-day dump of `ssf_recording`;
- early erasure and what to do after restoring the database.

It assumes recording-keys-deployment.md and archive-storage-deployment.md are
done. Recording itself stays off until Step 9.

Follow the steps top to bottom. Each one says what to expect; output that
differs should stop the rollout rather than be repeated.

## What each part can and cannot do

- **The database decides.** Each conversation's retention date and legal hold
  change only through `retention_decisions` rows, which a trigger applies. A
  date is never moved earlier, and a shredded conversation takes no decision,
  key wrap or chain entry. Supervisors decide through the gateway's routes
  (`/api/admin/recording/conversations`), with `ssf.recording.supervise` and a
  fresh MFA login.
- **One worker per archive site.** Each holds only its own site's `retention`
  pair, and reaches `ssf_recording` over the link.

  | Worker | Database role | May |
  |---|---|---|
  | primary (archive VM) | `ssf_recording_retention` | track and change locks and holds on the primary; shred expired conversations; delete their rows once both sites are clear; record operator erasures |
  | replica (replica VM) | `ssf_recording_replica` | track and change locks and holds on the replica; record that its site is clear. It cannot shred, delete a row or erase |

  No worker holds the gateway's signing key, blob key or writer credentials,
  and no role bypasses row-level security.
- **A hold is lifted only by a supervisor's later `hold_off`.** A worker that
  finds the database behind the audit position it last saw (a restore) stops
  every destructive step until an operator acknowledges it (Step 11).
- **Expiry**, on the retention date, for a conversation that has ended (or
  started more than 24 hours ago) and has no hold: the key wraps are deleted
  first, so the content is unreadable at once. Each site then deletes the
  versions once their lock lapses, about a day later; once both sites list
  nothing for the conversation, its rows go. The audit events and the
  decisions stay.

## Every command names its stack

On the gateway host:

```bash
source scripts/lib/production-common.sh
```

On the archive VM and the replica VM, define the functions from
archive-storage-deployment.md, "Every command names its stack".

## Step 1 — Before you start

Take a dump of `ssf_recording` into the directory the daily dumps use, so it
is pruned after 14 days like them rather than kept for good:

```bash
install -d -m 0700 backups/recording
(umask 077 && production_compose exec -T ssf-postgres sh -ec \
  'exec pg_dump -U "$POSTGRES_USER" -d ssf_recording' \
  | gzip -c > "backups/recording/ssf-recording-before-004-$(date -u +%Y%m%d_%H%M%S).sql.gz")
```

## Step 2 — Passwords and migration 004

Add two passwords to `.env` on the gateway host, each from
`openssl rand -base64 32`, and store both in the operator's password manager:

```
SSF_RECORDING_RETENTION_PASSWORD=<primary worker's password>
SSF_RECORDING_REPLICA_PASSWORD=<replica worker's password>
```

Recreate the database container so it sees them, then apply:

```bash
production_compose up -d ssf-postgres
production_compose exec -T ssf-postgres /docker-entrypoint-initdb.d/apply.sh
```

Feedback submissions answer a retryable 503 for a few seconds meanwhile.
Expected, after the earlier lines:

```
apply.sh: applying /docker-entrypoint-initdb.d/recording/migrations/004_recording_retention.sql to ssf_recording
apply.sh: done
```

Check that no recording role bypasses row-level security:

```bash
production_compose exec -T ssf-postgres sh -ec \
  'psql -U "$POSTGRES_USER" -d ssf_recording -tAc "SELECT rolname, rolbypassrls FROM pg_roles WHERE rolname LIKE '\''ssf_recording%'\'' ORDER BY 1"'
```

Expected: three lines, `ssf_recording_app|f`, `ssf_recording_replica|f` and
`ssf_recording_retention|f`.

## Step 3 — The link to the database

The replica VM accepts no inbound connection, so both workers connect out to
the gateway host. Add the gateway host as a peer of the private link between
the archive VM and the replica (archive-storage-deployment.md, Step 1). Below,
its link address is `10.8.0.3`; the archive VM is `10.8.0.1` and the replica
`10.8.0.2`.

**Start Docker after the link.** Docker cannot publish a port on an address
that does not exist yet, and then `ssf-postgres` does not start, which takes
feedback and recording down with it. With the link as `wg-quick@wg0` (use its
real name below):

```bash
sudo mkdir -p /etc/systemd/system/docker.service.d
printf '[Unit]\nAfter=wg-quick@wg0.service\nWants=wg-quick@wg0.service\n' \
  | sudo tee /etc/systemd/system/docker.service.d/after-wireguard.conf
sudo systemctl daemon-reload
systemctl show docker -p After | grep -c wg-quick@wg0
```

Expected: `1`.

Publish the database on that address only. In `.env` on the gateway host:

```
SSF_RECORDING_DB_PUBLISH=10.8.0.3:5432
```

Admit the two VMs and nobody else on the link, in `DOCKER-USER` as for the
archive ports, made persistent the way the host keeps its other rules. The
rules name the link interface: without `-i`, a host that filters bridged
traffic would also drop the gateway's own connections to its database. Each
`-I` goes on top, so the `DROP` is inserted first:

```bash
sudo iptables -I DOCKER-USER -i wg0 -p tcp -m conntrack --ctorigdstport 5432 --ctdir ORIGINAL -j DROP
sudo iptables -I DOCKER-USER -i wg0 -p tcp -m conntrack --ctorigdstport 5432 --ctdir ORIGINAL -s 10.8.0.2 -j RETURN
sudo iptables -I DOCKER-USER -i wg0 -p tcp -m conntrack --ctorigdstport 5432 --ctdir ORIGINAL -s 10.8.0.1 -j RETURN
production_compose up -d ssf-postgres
sudo docker port ssf-backend-ssf-postgres-1
production_compose exec -T api_gateway python -c \
  "import socket; socket.create_connection(('ssf-postgres', 5432), 3); print('gateway reaches its database')"
```

Expected: `5432/tcp -> 10.8.0.3:5432`, then `gateway reaches its database`.
Then, from each VM:

```bash
nc -vz 10.8.0.3 5432
```

Expected: `succeeded` (or `open`) from both VMs, and a timeout from any other
host on the link.

## Step 4 — The image on each VM

The workers run the gateway's image. On the gateway host, with the tag the
production compose file names for `api_gateway`:

```bash
sudo docker save ssf-backend-api_gateway:prod-<sha> | gzip > ssf-gateway-image.tar.gz
```

Copy it to both VMs, then on each:

```bash
gunzip -c ssf-gateway-image.tar.gz | sudo docker load
rm ssf-gateway-image.tar.gz
```

Add to `/etc/ssf-archive/archive.env` on the archive VM:

```
SSF_RETENTION_IMAGE=ssf-backend-api_gateway:prod-<sha>
SSF_RETENTION_DATABASE_URL=postgresql://ssf_recording_retention@10.8.0.3:5432/ssf_recording
```

and to `/etc/ssf-archive/replica.env` on the replica VM:

```
SSF_RETENTION_IMAGE=ssf-backend-api_gateway:prod-<sha>
SSF_RETENTION_DATABASE_URL=postgresql://ssf_recording_replica@10.8.0.3:5432/ssf_recording
```

Copy the updated `deploy/archive-storage/` compose files to `/opt/ssf-archive/`
on both VMs. Repeat this step whenever the gateway is deployed with a change
under `services/api_gateway/recording/`.

## Step 5 — Secrets on each VM

The image runs as `app`, uid 100 and gid 101 (recording-keys-deployment.md,
Step 1). Each VM gets its own site's `retention` pair, the one created in
archive-storage-deployment.md Step 2, and never the other site's. On the
archive VM, type the pair and the primary worker's database password in without
echoing them:

```bash
sudo install -d -m 0500 -o 100 -g 101 /etc/ssf-archive/retention
read -rs KEY && read -rs SECRET && read -rs PASSWORD
printf '{"access_key_id": "%s", "secret_access_key": "%s"}\n' "$KEY" "$SECRET" \
  | sudo tee /etc/ssf-archive/retention/s3-retention.json > /dev/null
printf '%s\n' "$PASSWORD" | sudo tee /etc/ssf-archive/retention/database-password > /dev/null
unset KEY SECRET PASSWORD
# In a root shell: an unprivileged one cannot expand the glob under /etc/ssf-archive.
sudo sh -c 'chown 100:101 /etc/ssf-archive/retention/* && chmod 0400 /etc/ssf-archive/retention/*'
```

On the replica VM, the same with the replica's pair and the replica worker's
password.

## Step 6 — Start and verify

On the archive VM:

```bash
archive_compose --profile retention up -d retention
archive_compose --profile retention exec -T retention \
  python -m services.api_gateway.recording.retention once
```

On the replica VM, the same with `replica_compose`. A pass beside the running
loop is safe: both bring the same rows to the same state.

Expected: one JSON line with `"halted": false` and `"failures": 0`. A failure
names only an error type in the container's log
(`archive_compose --profile retention logs retention`):

- `RecordingStorageUnavailable`: the database is unreachable or refused the
  password. Check Step 3 and `database-password`.
- `ArchiveUnavailableError`: the site's S3 API does not answer.
- `ArchiveConfigError` at start: a file in `/etc/ssf-archive/retention` is
  missing, unreadable for uid 100, or malformed.

On the gateway host, each site has a fresh heartbeat:

```bash
production_compose exec -T ssf-postgres sh -ec \
  'psql -U "$POSTGRES_USER" -d ssf_recording -c "SELECT site, beat_at, halted, failing_seconds, hold_mismatches FROM retention_worker_status"'
curl -s http://127.0.0.1:8000/metrics | grep -c '^ssf_retention'
```

Expected: a `primary` and a `replica` row, each beaten in the last five minutes
with `halted` false; and `8` series (four per site) within a minute of the
gateway reading them.

## Step 7 — The daily dump

Add to root's crontab on the gateway host:

```cron
15 2 * * * /root/projects/ssf-backend/scripts/backup-recording.sh >> /var/log/ssf-backup-recording.log 2>&1
```

Run it once by hand:

```bash
scripts/backup-recording.sh
ls -l backups/recording/
```

Expected: `Recording backup completed: …/ssf-recording-<timestamp>.sql.gz`, and
the file with mode `-rw-------`. Every run first deletes each `*.sql.gz` in
`backups/recording/` older than 14 days, whether or not its own dump succeeds,
the Step 1 dump included. Never copy these dumps anywhere else: a copy outside
that directory outlives the 14 days within which a shredded conversation must
be gone from every backup.

## Step 8 — Supervisors

Supervisors need `ssf.recording.supervise` in Studio and the step-up MFA of
recording-keys-deployment.md, Step 6. The routes are API only for now; the
screens are a separate issue.

## Step 9 — Turning recording on

Only now set `SSF_ARCHIVE_ENDPOINT` (archive-storage-deployment.md, Step 6).
recording-mode-cutover.md keeps it empty until this step is reached.

## Step 10 — Early erasure

For a court order or another decision to erase before the retention date. It
runs on the archive VM only; the replica's worker refuses it.

```bash
archive_compose --profile retention exec -T retention \
  python -m services.api_gateway.recording.retention erase \
  --tenant <tenant id> --conversation <conversation id> \
  --reason "<case reference>" --operator <your name>
```

Expected: `erased <conversation id>: decision <id>`. The key wraps are gone at
once; the versions follow when their locks lapse. The decision, its audit event
and a line in `/var/lib/ssf-retention/erasures.log` on the archive VM record it.

It refuses, exit status 1, with:

- `legal_hold_set`: a supervisor must lift the hold first.
- `version_held`: a site still holds one of its versions without a hold in the
  database (`RecordingRetentionHoldMismatch`); resolve that first.
- `conversation_live`: the conversation has not ended; end the session first.
- `conversation_shredded` or `no_conversation`: it is erased or expired already,
  or the ID is wrong.

Exit status 3, `erasure committed but not logged: {…}`: the erasure happened,
but the log line could not be written. Append the printed JSON yourself:

```bash
archive_compose --profile retention exec -T retention \
  sh -c 'cat >> /var/lib/ssf-retention/erasures.log' <<'EOF'
<the printed JSON line>
EOF
```

The log is what lets an erasure survive a restore of an older dump. Keep an
offline copy of it with the operator's records after each erasure.

## Step 11 — After restoring `ssf_recording`

A restored dump knows nothing of what happened after it was taken: erasures,
holds, extensions, expiries. The store still has the holds and extended locks
set since then, so the workers read every version from the store again and
compare. In this order:

1. Stop both workers: `archive_compose --profile retention stop retention`,
   and `replica_compose` likewise.
2. Restore the dump.
3. Start the workers. Their first pass finds the database behind the audit
   marks they kept: both report `"halted": true` and
   `RecordingRetentionWorkerHalted` fires. From then on they extend and hold,
   but shred, lift and delete nothing, and they read every version's lock and
   hold from the store again.
4. Repeat every erasure the dump does not know, on the archive VM:

   ```bash
   archive_compose --profile retention exec -T retention \
     python -m services.api_gateway.recording.retention replay-erasures --operator <your name>
   ```

   Expected: `replayed N, skipped M, refused 0`. Skipped are erasures the dump
   already held or conversations it never had. A refusal names the
   conversation and the reason: `legal_hold_set` needs a supervisor to lift the
   hold, `conversation_live` clears once the gateway ends the orphaned
   conversation (within a minute), `version_held` once step 5 is done; then run
   the command again.
5. Ask each worker what the restore lost, on both VMs:

   ```bash
   archive_compose --profile retention exec -T retention \
     python -m services.api_gateway.recording.retention acknowledge-restore --operator <your name>
   ```

   It acknowledges only once every version has been read again and nothing is
   left to explain. Otherwise it changes nothing, exits 1 and prints:

   - `… tenants not yet re-read`: run it again after the worker's next pass.
   - one line per version, `<reason> <tenant> <conversation>`:
     - `not_yet_read`: the worker has not read it yet; wait a pass.
     - `held_without_hold`: a hold set after the dump. Have a supervisor set
       the hold again with its original reason.
     - `locked_beyond_date … until <date>`: locked more than three days past
       the conversation's date, most likely an extension set after the dump.
       Have a supervisor extend it again to the date shown.

   Run it again until it prints `restore acknowledged by <name>: N tenants,
   destructive steps resume`. A listed version you have checked and found
   explained (for example, a tenant whose retention was raised after the
   conversation started) can be accepted with `--accept-conflicts`, once every
   other line is resolved.
6. Check that `RecordingRetentionWorkerHalted` clears within a pass.

## Alerts

| Alert | What to do |
|---|---|
| `RecordingRetentionWorkerSilent` | That site's worker has not finished a pass for 30 minutes. Check the container (`… --profile retention ps`, `… logs retention`) and Step 3's link. |
| `RecordingRetentionWorkerFailing` | A step on that site has failed for a day. The log names the error type; Step 6 lists the usual causes. |
| `RecordingRetentionWorkerHalted` | The database is behind the worker's audit mark. If it was restored on purpose, work through Step 11. If not, find out why before acknowledging anything. |
| `RecordingRetentionHoldMismatch` | Versions are held on that site with no hold in the database and no later `hold_off`, or untracked versions there are held. After a restore, have a supervisor set the hold again (Step 11, item 5). Otherwise check the conversation's decisions in the audit log; a supervisor's `hold_off` lifts it. For a shredded conversation no decision is accepted any more: lift the hold on that site with its retention pair by hand, and record why. |

## Rollback

Stop both workers (`archive_compose --profile retention stop retention`, and
`replica_compose` likewise). Nothing then expires and nothing is deleted; locks
keep protecting the archive. Migration 004 stays: its tables are unused without
the workers, and the gateway's routes keep working.

## Known limits

- Root on an archive VM holds that site's retention pair: it can extend locks
  there without bound and lift that site's holds (spec §19).
- Backups stay on the gateway host. Losing the host loses every key wrap, and
  with it every archive (accepted 2026-10-28).
- Audit events are never pruned yet.
- A hold the worker finds on a version without having applied it counts from
  that moment; only a `hold_off` decided later lifts it, so a quick on-off
  before a version reached the replica leaves a mismatch to clear by hand.
