# Keycloak Operations Runbook

Keycloak is public only through Traefik at `https://auth.kassel.smartspeechflow.de`.
Its PostgreSQL database and management endpoint remain private to the Compose network.
This infrastructure does not yet authenticate SSF users.

## First deployment

Confirm DNS resolves to the SSF host before starting Keycloak:

```bash
test "$(dig +short A auth.kassel.smartspeechflow.de | head -n1)" = "$(dig +short A translate.smart-village.solutions | head -n1)"
```

If this fails, stop: Traefik cannot obtain a TLS certificate. Generate database
and bootstrap-admin passwords with `openssl rand -base64 32`, set the required
`KEYCLOAK_*` values only in the ignored `.env`, then run `chmod 600 .env`.

```bash
docker compose build keycloak
docker compose up -d keycloak-postgres keycloak
docker compose ps keycloak-postgres keycloak
```

## Verification

```bash
docker compose exec -T keycloak bash -ec 'exec 3<>/dev/tcp/127.0.0.1/9000; printf "GET /health/ready HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n" >&3; grep -q "200 OK" <&3'
curl --fail --silent --show-error https://auth.kassel.smartspeechflow.de/realms/master >/dev/null
docker inspect "$(docker compose ps -q keycloak-postgres)" --format '{{json .HostConfig.PortBindings}}'
```

The first two commands must pass and the final command must return `{}`. Verify
the bootstrap administrator with `kcadm.sh` without printing its password, then
rotate the initial administrator password after first login.

## Backup and recovery

Before every upgrade, create an encrypted compressed PostgreSQL logical backup
with `pg_dump`, store a SHA-256 checksum, and restore it into a temporary
database to verify it. Review Keycloak migration notes, change only the pinned
Keycloak tag, rebuild, recreate only Keycloak, and repeat verification. On
failure, restore the preceding pinned tag; never remove `keycloak-postgres-data`.

Never expose PostgreSQL or Keycloak management port 9000 to work around an
incident.

## References

- [Keycloak container guide](https://www.keycloak.org/server/containers)
- [Keycloak reverse-proxy configuration](https://www.keycloak.org/server/reverseproxy)
