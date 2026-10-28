# Archive Storage Deployment Runbook

## Scope

This runbook sets up the archive store of recording mode (#613): a SeaweedFS
server on its own VM, an off-site replica that pulls from it, the gateway's
access, and one bucket per tenant. Nothing is archived yet; that arrives with
#615. The gateway only gains the configuration and the `check` command.

Everything here is optional per host. With `SSF_ARCHIVE_ENDPOINT` empty the
gateway behaves as before.

Follow the steps top to bottom. Each one says what to expect; output that
differs should stop the rollout rather than be repeated.

## What protects the archive

- **Object Lock in compliance mode.** Every tenant bucket locks each object
  version from its upload for the bucket's default retention. No credential,
  the admin's included, can delete a locked version or shorten its lock.
  Retention can only be extended.
- **Only the S3 API enforces the lock.** SeaweedFS's filer, master and volume
  servers below it do not. So the primary publishes S3 (8333) to the gateway,
  and the filer's two ports (8888, 18888) to the replica, nothing else.
  `security.toml` makes the filer and the volume servers refuse unsigned writes
  and deletes. The filer's gRPC port (18888) has no authentication, though:
  whoever controls the replica VM could delete on the primary through it. So
  the replica VM accepts no inbound connection except restores.
- **Credentials:**

  | Identity | Held by | May |
  |---|---|---|
  | `admin` | the operator, typed in for one command at a time | create buckets, set their default retention |
  | `retention` | the retention worker (#618), one per site | read and extend retention, set legal holds, list and delete versions whose lock has lapsed |
  | `writer-<tenant_ref>` | the gateway, one per tenant | put and read objects, list, and read the lock configuration, in that tenant's bucket only |

  `retention` and the writers are confined by policies that name each S3
  action. SeaweedFS's older `Write` grant would also let them add an expiry
  rule or change CORS on the bucket.
- **Root on the primary is not stopped by any of this** (spec §19). The signed,
  timestamped chain (#615) makes tampering detectable. The replica pulls, so the
  primary holds no credential for it and cannot reach it, and a version deleted
  on the primary stays on the replica. **The replica does not survive a
  compromised primary**, though: whoever holds the primary's filer key can
  rewrite a version entry there, and the sync then replaces the replica's copy
  and drops its lock (verified 2026-10-27). What the replica protects against is
  the loss of the primary, deletions, and anything done through the S3 API.

## Every command names its stack

On the gateway host:

```bash
source scripts/lib/production-common.sh
```

On the archive VM, and on the replica VM, define once per shell:

```bash
archive_compose() { sudo docker compose --project-name ssf-archive --env-file /etc/ssf-archive/archive.env --file /opt/ssf-archive/docker-compose.yml "$@"; }
replica_compose() { sudo docker compose --project-name ssf-archive-replica --env-file /etc/ssf-archive/replica.env --file /opt/ssf-archive/docker-compose.replica.yml "$@"; }
```

## Step 1 — Two VMs and the private link

- **The archive VM** on the production host, with Docker, the Compose plugin
  and `python3`, and a private address the gateway containers reach (below:
  `10.0.0.5`). Its disk holds tens of GB per tenant per year (spec §12.4).
- **The replica VM** at another location, with the same disk and software.
- **A private link** between them, for example WireGuard. Below, the archive
  VM's link address is `10.8.0.1` and the replica's `10.8.0.2`. The replica
  must exist before production go-live (spec §12.1).

Copy `deploy/archive-storage/` from this repository to both VMs, for example to
`/opt/ssf-archive/`.

**Firewall.** Docker publishes ports through its own NAT rules, which
ufw and firewalld do not see. Restrict them in the `DOCKER-USER` chain, and make
the rules persistent the way the host keeps its others:

```bash
# On the archive VM: S3 from the gateway host only, the filer from the replica only.
sudo iptables -I DOCKER-USER -p tcp -m conntrack --ctorigdstport 8333 --ctdir ORIGINAL ! -s <gateway host address> -j DROP
sudo iptables -I DOCKER-USER -p tcp -m conntrack --ctorigdstport 8888 --ctdir ORIGINAL ! -s 10.8.0.2 -j DROP
sudo iptables -I DOCKER-USER -p tcp -m conntrack --ctorigdstport 18888 --ctdir ORIGINAL ! -s 10.8.0.2 -j DROP

# On the replica VM: S3 from the address restores are run from only.
sudo iptables -I DOCKER-USER -p tcp -m conntrack --ctorigdstport 8333 --ctdir ORIGINAL ! -s <restore host address> -j DROP
```

## Step 2 — Configuration on each VM

SeaweedFS runs as the image's `seaweed` user and must read its files. Find its
numbers first:

```bash
sudo docker run --rm --entrypoint id chrislusf/seaweedfs@sha256:4e61d15fd35994cb1e43e1e553dff106794841fd9a99ade2fc8c8bfce4d7872d seaweed
# uid=1000(seaweed) gid=1000(seaweed) ...  -- use the numbers this prints
sudo install -d -m 0700 /etc/ssf-archive
sudo install -d -m 0700 -o 1000 -g 1000 /etc/ssf-archive/seaweedfs
```

**Keys.** Copy `security.example.toml` to `/etc/ssf-archive/seaweedfs/security.toml`
and fill both keys with `openssl rand -hex 32`. Each VM gets its own.

**Identities.** Copy `s3.example.json` to `/etc/ssf-archive/seaweedfs/s3.json`.
Replace each `REPLACE` with a fresh value: access keys with
`openssl rand -hex 10`, secret keys with `openssl rand -base64 30`. Store each
VM's admin pair in the operator's password manager, and its retention pair for
#618. None of them goes onto the gateway host.

```bash
sudo chown 1000:1000 /etc/ssf-archive/seaweedfs/*
sudo chmod 0400 /etc/ssf-archive/seaweedfs/*
```

**Addresses.** On the archive VM, `/etc/ssf-archive/archive.env`:

```
SSF_ARCHIVE_LISTEN_ADDRESS=10.0.0.5
SSF_ARCHIVE_LINK_ADDRESS=10.8.0.1
```

On the replica VM, `/etc/ssf-archive/replica.env`:

```
SSF_ARCHIVE_LISTEN_ADDRESS=<the address restores are run from>
SSF_ARCHIVE_PRIMARY_FILER=10.8.0.1:8888
```

```bash
sudo chmod 0600 /etc/ssf-archive/*.env
```

## Step 3 — Start and verify the primary

On the archive VM:

```bash
archive_compose up -d
curl -s -o /dev/null -w "%{http_code}\n" http://10.0.0.5:8333/
sudo docker port ssf-archive-seaweedfs-1
sudo docker exec ssf-archive-seaweedfs-1 sh -c 'wget -q -O- --post-data=x "http://$(hostname -i):8888/buckets/probe" 2>&1'
sudo docker exec ssf-archive-seaweedfs-1 sh -c 'wget -q -O- --post-data=x "http://$(hostname -i):8080/3,01637037d6" 2>&1'
```

Expected, in order: `403` (S3 answers and wants a signature); exactly three
lines, `8333/tcp -> 10.0.0.5:8333`, `8888/tcp -> 10.8.0.1:8888` and
`18888/tcp -> 10.8.0.1:18888`; and twice `wget: server returned error:
HTTP/1.1 401 Unauthorized`, from the filer and from the volume server. Anything
else, above all a write that succeeds, stops the rollout: the lock could then be
bypassed.

## Step 4 — Start and verify the replica

On the replica VM:

```bash
replica_compose up -d
sudo docker port ssf-archive-replica-seaweedfs-1
sudo docker port ssf-archive-replica-primary-sync-1
```

Expected: one line, `8333/tcp -> <restore address>:8333`, and nothing for the
sync. A minute later:

```bash
sudo docker logs --since 30s ssf-archive-replica-primary-sync-1 2>&1 | grep -c '^E'
```

Expected: `0`. Error lines in the first seconds after a start, while the
replica's own filer comes up, are normal.

The sync copies every new version with its lock to the replica, which then
enforces the lock itself. It never copies a deletion, and it skips a change that
leaves a version's content as it was: a version deleted on the primary stays on
the replica, and an extension or legal hold set on the primary does not reach
it. The retention worker (#618) applies both to the replica through the
replica's own S3 API and retention identity. A change to a version's content
does reach the replica; only a write below the S3 API on the primary can make
one (see "What protects the archive").

## Step 5 — Onboard a tenant

Repeat for every tenant that will record. The retention is the tenant's
`recording.retentionHours` (Studio, #612); until Studio supplies it, the value
agreed with the tenant.

1. **Writer credential**, on the gateway host. The command writes it to a file
   only you can read; nothing secret appears on screen. `merge_writer.py` adds
   it to the gateway's writers file, which it rewrites with mode 0400 for the
   gateway's numbers (the ones `recording-keys-deployment.md` Step 1 found):

   ```bash
   (umask 077 && production_compose run --rm --no-deps -T api_gateway \
     python -m services.api_gateway.recording.storage.admin new-writer tenant-kassel \
     > new-writer-tenant-kassel.json)
   sudo python3 deploy/archive-storage/merge_writer.py gateway new-writer-tenant-kassel.json \
     /etc/ssf/recording-secrets/archive-writers.json --owner 100:101
   ```

   Copy `new-writer-tenant-kassel.json` to the archive VM, for example with
   `scp`, and add its identity and policy to `s3.json` there:

   ```bash
   sudo python3 /opt/ssf-archive/merge_writer.py seaweedfs new-writer-tenant-kassel.json \
     /etc/ssf-archive/seaweedfs/s3.json --owner 1000:1000
   shred -u new-writer-tenant-kassel.json
   ```

   Expected on each host: `merge_writer.py: <file> updated, mode 0400, owner
   <numbers>`. Then `shred -u` the file on the gateway host as well. The script
   refuses a target that is not valid JSON and leaves it as it was. After any
   edit of `s3.json` by hand, check it and restore its permissions:

   ```bash
   sudo python3 -m json.tool /etc/ssf-archive/seaweedfs/s3.json > /dev/null \
     && sudo chown 1000:1000 /etc/ssf-archive/seaweedfs/s3.json \
     && sudo chmod 0400 /etc/ssf-archive/seaweedfs/s3.json
   ```

2. **Reload the identities** on the archive VM. SeaweedFS reloads `s3.json` on
   SIGHUP, but not the policies in it, so restart it. Uploads pause for about
   half a minute, and the replica's sync restarts itself and resumes.

   ```bash
   archive_compose restart seaweedfs
   ```

3. **Bucket**, on the gateway host. Type the admin pair in without echoing it,
   so it reaches neither the screen nor the shell history:

   ```bash
   read -rs SSF_ARCHIVE_ADMIN_ACCESS_KEY_ID && export SSF_ARCHIVE_ADMIN_ACCESS_KEY_ID
   read -rs SSF_ARCHIVE_ADMIN_SECRET_ACCESS_KEY && export SSF_ARCHIVE_ADMIN_SECRET_ACCESS_KEY
   production_compose run --rm --no-deps -e SSF_ARCHIVE_ENDPOINT=http://10.0.0.5:8333 \
     -e SSF_ARCHIVE_ADMIN_ACCESS_KEY_ID -e SSF_ARCHIVE_ADMIN_SECRET_ACCESS_KEY \
     api_gateway python -m services.api_gateway.recording.storage.admin \
     create-bucket tenant-kassel --retention-hours 8760
   unset SSF_ARCHIVE_ADMIN_ACCESS_KEY_ID SSF_ARCHIVE_ADMIN_SECRET_ACCESS_KEY
   ```

   Expected: `ssf-rec-<ref>: object lock on, default compliance retention 366
   days (new)`. The default is the retention rounded up to whole days, plus
   one, so a lock never ends before the conversation's retention date. Content
   becomes unreadable on that date regardless, because expiry deletes the key
   wraps first (spec §16).

   Running it again is safe and prints the previous default as `(was N)`. A
   tenant whose retention changes gets `create-bucket` again with the new
   hours: that sets the default for new versions, and existing versions keep
   theirs until the retention worker extends them. A smaller number than
   before shortens the locks of everything recorded from then on, so confirm
   it is meant.

   It refuses a bucket that exists without Object Lock
   (`bucket_without_object_lock`); such a bucket cannot be repaired and must be
   removed by hand while it is empty.

4. **Check it** as in Step 6, before the tenant records. From #615 on, the
   gateway reads `archive-writers.json` at start, so restart it after a change
   with `production_compose up -d --force-recreate api_gateway`.

## Step 6 — Connect the gateway

Add to `.env` on the gateway host:

```
SSF_ARCHIVE_ENDPOINT=http://10.0.0.5:8333
```

```bash
production_compose up -d api_gateway
production_compose exec -T api_gateway python -m services.api_gateway.recording.storage.admin check
```

Expected: one `ok    <tenant> ssf-rec-<ref> <days> days` line per tenant in
`archive-writers.json`, and exit status 0. A failing tenant prints `FAIL` and a
code:

- `InvalidAccessKeyId`: the archive VM has not been restarted since its
  identity was added.
- `AccessDenied`: the identity is there but its policy is not.
- `no_default_retention`: `create-bucket` did not finish; run it again.
- `network_error`: the gateway cannot reach the VM.

The connection is plain HTTP on the private network. Requests are signed, and
every upload carries a signed SHA-256 checksum of its body that the store
checks, so a body altered in transit is refused (`BadDigest`; CI tests this).
The objects are ciphertext before they leave the gateway. The client never
follows a redirect.

## Step 7 — Verify the guarantees on the real stores

The integration tests that CI runs against a throwaway pair also run against
the real ones. Use a dedicated tenant ID, `verification`, onboarded as in
Step 5 with `--retention-hours 1`, so its test objects stay locked for two days
only. Then, on a host that reaches both S3 ports, in a checkout of this
repository with `requirements-dev.txt` and the gateway requirements installed,
type each `<key>:<secret>` pair in without echoing it:

```bash
export SSF_ARCHIVE_TEST_REQUIRED=1 SSF_ARCHIVE_TEST_TENANT=verification
export SSF_ARCHIVE_TEST_ENDPOINT=http://10.0.0.5:8333
export SSF_ARCHIVE_TEST_REPLICA_ENDPOINT=http://<replica restore address>:8333
for name in ADMIN WRITER RETENTION REPLICA_ADMIN; do
  read -rs "SSF_ARCHIVE_TEST_$name" && export "SSF_ARCHIVE_TEST_$name"
done
pytest --run-integration -q tests/integration/test_archive_storage.py -k "not without_lock"
```

`ADMIN` and `RETENTION` are the archive VM's pairs, `WRITER` the
`verification` tenant's, and `REPLICA_ADMIN` the replica's admin pair.

Expected: `26 passed, 1 deselected`. The deselected test creates a bucket
without Object Lock on purpose, which does not belong in production. The tests
clean up what they can: the second tenant's bucket they create
(`verification-other`) is removed again, nothing is left under a legal hold,
and a bucket change that should have been refused is taken back before the
test fails. The test objects stay in the `verification` bucket; once their
two-day lock has lapsed, the retention identity may delete them.

## Rollback

Unset `SSF_ARCHIVE_ENDPOINT` and run `production_compose up -d api_gateway`.
The store and its locked objects stay; nothing can delete them early, by
design.

## Known limits

- An identity change needs a SeaweedFS restart (Step 5), about half a minute
  without uploads. Once #615 records, its spool holds them meanwhile.
- Each tenant has its own spool and upload queue on the gateway volume
  `archive-spool` (`/data/archive-spool/<tenant_ref>/`, #615). A lasting fault
  for one tenant (no writer credential, no bucket, an identity without its
  policy) stops that tenant's uploads until it is fixed, and once its spool is
  full, that tenant's recordings pause. Other tenants are unaffected. `check`
  still runs before a tenant records.
- The replica does not survive root on the primary: a version rewritten below
  the S3 API there replaces the replica's copy (see "What protects the
  archive"). The chain still shows the tampering.
- Nothing alerts on a stopped or lagging sync yet (#626); Step 4's log check
  is the only signal.
- The archive VM's disk is in no `backup-production.sh` artifact. The replica
  is its copy.
- Restoring from the replica: it holds the same buckets, keys and version IDs,
  so the gateway can read from it once it has writer identities there and
  `SSF_ARCHIVE_ENDPOINT` points to it. The procedure belongs to #620.
