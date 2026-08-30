## Context

The desired operational objectives are a five-minute recovery time after a
reboot and a 24-hour maximum data loss. Backups remain local by explicit
decision.

## Goals / Non-Goals

- Goals: deterministic deployment, automatic reboot recovery, complete local
  backups, observable failures, and controlled rollback.
- Non-Goals: multi-host high availability, off-host backup replication, and
  automated application-image upgrades.

## Decisions

- Use one pinned `docker-compose.production.yml` as the production source of
  truth.
- Use systemd to order Docker Compose startup after Docker and NVIDIA
  readiness, and run a five-minute health gate.
- Use native database backups plus complete volume and bind-mount archives;
  verify them through a manifest rather than a symlink.
- Retain seven daily, four weekly, and twelve monthly backups.

## Risks / Trade-offs

- Local backups cannot recover a lost host. This is accepted by the operator.
- Reconciliation must first pin the known-good running images to avoid an
  accidental application upgrade.

## Migration Plan

1. Inventory the live images and configuration.
2. Add and validate the canonical definitions without changing live recovery.
3. Run a controlled reboot test.
4. Enable canonical recovery, then remove superseded paths and orphaned
   containers.

## Open Questions

None.
