# Production Operations Stability Design

## Context

The production server currently runs a healthy workload, but its running
containers and the repository Compose configuration have drifted apart. A
reboot also exposed an uninstalled NVIDIA kernel module. Existing backup jobs
do not consistently include every persistent volume and their verifier follows
the `latest` symlink incorrectly.

## Goals

- Restore every production service automatically within five minutes of a host
  reboot.
- Treat one versioned production Compose definition as the source of truth.
- Prevent implicit application-image upgrades during recovery.
- Provide verified local backups with a maximum data-loss objective of 24
  hours.
- Make failed recovery, backup, and health checks observable.

## Non-Goals

- High availability across multiple hosts.
- Off-host backup storage. A complete server or storage loss remains outside
  the agreed recovery scope.
- Automatic application-image upgrades.

## Decisions

### Canonical production definition

A single versioned `docker-compose.production.yml` SHALL describe every
production service, including Keycloak. Images SHALL use fixed versions or
immutable digests; `latest` SHALL not be used. The initially committed values
will match the proven running production images. Application image updates are
separate, reviewed deployments.

### Reboot recovery

A systemd unit SHALL run after Docker and NVIDIA driver availability and start
only the canonical production Compose definition. It SHALL invoke a health
verification script and fail if the expected workload has not recovered within
five minutes. The script SHALL check the API dependency health, Keycloak,
Prometheus, Grafana, ClickHouse, Redis, Ollama, and NVIDIA availability.

The NVIDIA generic module metapackage SHALL remain installed so future kernel
updates pull a matching driver module.

### Backups

A daily systemd timer SHALL produce a complete local backup. It SHALL use
native consistent backups for databases where available and archive every
project-owned persistent volume and required bind-mounted data, configuration,
and TLS material. Backup verification SHALL read every archive and validate a
manifest of expected artifacts without using a symlink as the data source.

Retention SHALL be seven daily, four weekly, and twelve monthly backups. A
monthly restore drill SHALL validate recovery of the critical data stores.

### Controlled updates and rollback

Operating-system updates SHALL be preceded by an upgrade simulation and a
fresh verified backup, followed by a reboot and the same five-minute health
verification. Application deployments SHALL validate the canonical Compose
configuration before changing a pinned version. A failed deployment SHALL be
rolled back by restoring the previous versioned Compose definition and image
set, followed by health verification.

## Risks and Mitigations

- Local-only backups do not survive host loss. This is an explicitly accepted
  limitation.
- Synchronizing the initial Compose definition can inadvertently change
  application versions. The migration records the current live image IDs and
  versions first, then tests the canonical definition before it replaces the
  existing boot behavior.
- GPU workloads depend on a matching host driver. The recovery health check
  tests `nvidia-smi` before accepting the deployment as healthy.

## Migration Plan

1. Record and pin the known-good running images and service configuration.
2. Add the canonical Compose definition, recovery unit, health check, and
   backup verifier without replacing the live boot path.
3. Test recovery in a controlled reboot and confirm all health checks finish
   within five minutes.
4. Enable the canonical recovery unit and retire the fragmented Compose boot
   paths.
5. Remove orphaned, never-started containers only after the canonical setup is
   verified.

## Verification

- `docker compose -f docker-compose.production.yml config --quiet` succeeds.
- A controlled reboot restores every expected container and health endpoint
  within five minutes.
- The backup verifier confirms all expected artifacts and readable archives.
- A monthly restore drill restores the critical stores into an isolated target.
