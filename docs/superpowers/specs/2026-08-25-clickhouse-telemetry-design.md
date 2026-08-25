# ClickHouse Telemetry and Consent-Governed Content Storage Design

## Context

SSF needs an internal analytical store for the conversation-quality KPI catalogue.
ClickHouse will run on the existing production-like Docker Compose host. The
installation must not expose a new public service or change the request path.

Some users may later give purpose-specific consent for SSF to retain source
text, ASR results, translations, and input or output audio. That content has
different privacy, access-control, retention, and deletion requirements from
analytics data.

## Goals

- Operate ClickHouse as a persistent, internal-only Docker Compose service.
- Document installation, verification, upgrade, backup, restore, rollback, and
  incident handling in English runbooks.
- Make ClickHouse ready for a future quality-telemetry implementation without
  creating tables or emitting events in this infrastructure change.
- Specify a separate future implementation change for KPI telemetry and
  consent-governed content storage.

## Non-Goals

- No API Gateway event emitter, ClickHouse schema, dashboard, or production
  telemetry data is introduced by the infrastructure change.
- No raw audio, text, transcripts, translations, IP addresses, or free-form
  errors are stored in ClickHouse.
- No public ClickHouse endpoint, Traefik route, or browser-accessible SQL UI is
  introduced.
- No content-storage implementation is included in the telemetry change.

## Decisions

### Internal ClickHouse deployment

Add a `clickhouse` service to `docker-compose.yml`, using a pinned
`clickhouse/clickhouse-server` image, `restart: always`, and an internal
`expose: 8123` declaration only. The service has no `ports` or Traefik labels.
It stores its data in the `clickhouse-data` named volume and uses
`ulimit nofile=262144`.

Database name, service user, and password are configured via `.env`; only
non-secret placeholders are added to `.env.example`. A missing password must
make Compose configuration invalid rather than falling back to a default. The
server is checked with `GET /ping` and administration is performed with
`docker compose exec clickhouse clickhouse-client`.

### Operational controls

The runbook will require a backup before an image update. Backups are logical,
compressed exports and follow the existing backup rotation. Restore is first
validated into a temporary database. Rollback stops or recreates the service
with the previous pinned image without removing the data volume.

### Telemetry and content boundary

ClickHouse is the analytical store only. The later telemetry capability writes
append-only, pseudonymised quality records with `event_id` and
`schema_version`. It records only the metadata needed by the KPI catalogue,
including an opaque `content_record_id_hash` where content exists.

Consented content uses a separate, tenant-isolated and encrypted content
store:

| Content class | Storage |
| --- | --- |
| Quality events, technical measurements, consent snapshots, opaque content references | ClickHouse |
| Source text, ASR results, translations, TTS text | Separate transactional content database |
| Input and output audio | Encrypted object store |
| Consent ledger, access audit, retention and deletion jobs | Transactional consent/content system |

Access to content must be purpose-, role-, and audit-controlled. Consent is
granular by purpose and content category, is never preselected, and is
withdrawable. On withdrawal, new content capture stops and existing content is
identified through the opaque reference and queued for deletion. ClickHouse
retains no content copies.

### Future OpenSpec change

Create `add-clickhouse-quality-telemetry` with a design document and delta
specifications. It will define the event contract, bounded taxonomy, async and
idempotent writes, failure isolation from the message path, retention, and test
coverage. It will also state the content-store boundary as a prerequisite, not
as an implementation task.

The implementation issue for a colleague must link to the OpenSpec proposal,
use the change ID as a label or title prefix, and list the proposal's acceptance
criteria. The issue cannot be considered complete until consent redaction,
deduplication, and a non-blocking ClickHouse failure path are tested.

## Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| ClickHouse outage delays messages | Future writer is asynchronous and best-effort; it never blocks the message path. |
| Unauthorised database access | No public port, dedicated password-protected user, credentials only in `.env`. |
| Content leaks into analytics | Contract allowlist, automated redaction tests, and separate content-store boundary. |
| Irrecoverable data or unsafe upgrade | Named volume, pre-upgrade backup, restore verification, pinned image, documented rollback. |
| Consent withdrawal is incomplete | Content references, deletion queue, deletion audit, and separate access-controlled content store. |

## Verification

The infrastructure change is accepted when Compose validates without exposing
ClickHouse externally; the service answers `/ping`; authenticated internal SQL
access works; the data survives recreation; and the runbook's backup and
restore verification commands succeed. The telemetry change has separate
automated tests for event allowlisting, consent redaction, idempotency, and
ClickHouse failure isolation.
