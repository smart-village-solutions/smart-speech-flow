# Keycloak Operations Runbook

Keycloak is public only through Traefik at `https://${KEYCLOAK_HOSTNAME}`.
Its PostgreSQL database and management endpoint remain private to the Compose network.
This infrastructure does not yet authenticate SSF users.

## First deployment

Set `KEYCLOAK_HOSTNAME` in the ignored deployment `.env`, export it for the
following checks, and confirm that its DNS record resolves to the SSF host
before starting Keycloak:

```bash
set -a
. ./.env
set +a
test -n "$(dig +short A "$KEYCLOAK_HOSTNAME" | head -n1)"
```

If this fails, stop: Traefik cannot obtain a TLS certificate. Generate database
and bootstrap-admin passwords with `openssl rand -base64 32`, set the required
`KEYCLOAK_*` values only in the ignored `.env`, then run `chmod 600 .env`.

```bash
docker compose build keycloak
docker compose up -d keycloak-postgres keycloak
docker compose ps keycloak-postgres keycloak
```

## KasselDIALOG login theme

The Keycloak image ships the `kasseldialog` login theme. It reuses the approved
KasselDIALOG header logo and the funding and Stadt Kassel footer logos from the
frontend while retaining Keycloak's standard login, recovery, OTP, and error
flows.

The local `ssf` realm selects this theme during import. Production tenant realms
are owned by Studio and are not imported by this Compose project. When creating
or updating such a realm, select `kasseldialog` as its **Login theme** under
**Realm settings → Themes** before making the realm available to users.

Realm import does not update an existing local `ssf` realm. After rebuilding
the Keycloak image, operators of an already initialized development stack must
select `kasseldialog` under **Realm settings → Themes** once, or update the
realm through `kcadm.sh` using their existing administrator session.

## Verification

```bash
docker compose exec -T keycloak bash -ec 'exec 3<>/dev/tcp/127.0.0.1/9000; printf "GET /health/ready HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n" >&3; grep -q "200 OK" <&3'
curl --fail --silent --show-error "https://${KEYCLOAK_HOSTNAME}/realms/master" >/dev/null
docker inspect "$(docker compose ps -q keycloak-postgres)" --format '{{json .HostConfig.PortBindings}}'
```

The first two commands must pass and the final command must return `{}`. Verify
the bootstrap administrator with `kcadm.sh` without printing its password, then
rotate the initial administrator password after first login.

## Backup and recovery

Before every upgrade, create an encrypted compressed PostgreSQL logical backup
with `pg_dump`, store a SHA-256 checksum, and restore it into a temporary
database to verify it. Review Keycloak migration notes, bind the tested image ID in the production
Compose file and `deploy/production/known-good-images.lock`, and recreate only
Keycloak. Verify the resolved local production tag against the locked image ID
before starting it; a tag alone is not an identity check. Keep both Dockerfile
base-image references pinned to the tested version and digest.

After a schema migration, an image-only downgrade is not a rollback. Keep
regular access and provisioning writers stopped, restore the verified preceding
Keycloak database backup with its original owner and required roles, and restore
the matching configuration and old image before private acceptance and reopening.
Never start the old image against a migrated schema or remove
`keycloak-postgres-data`. If access has already reopened, preserve and reconcile
intervening writes before restoring data.

The Kassel upgrade to 26.8.1 uses local reference
`ssf-keycloak:prod-2681-5ebdcb0`, locked to image ID
`sha256:03a99f77ebfa395d7d672feaeff6a2d1cb8676a2e03f417dfba6f09eafca9f10`.
The matching encrypted final dump, roles, configuration and evidence are retained
under `backups/kc-upgrade-26-8-1-20261025-kassel-live/`; private recipient keys stay
in its protected `keys/` directory. Earlier encrypted old-image archives remain
available in the preceding upgrade-probe backups. Do not delete rollback evidence
until retention is explicitly approved.

Never expose PostgreSQL or Keycloak management port 9000 to work around an
incident.

## References

- [Keycloak container guide](https://www.keycloak.org/server/containers)
- [Keycloak reverse-proxy configuration](https://www.keycloak.org/server/reverseproxy)
