# Production recovery and backup runbook

The production workload is defined only by
`deploy/production/docker-compose.production.yml`. It uses the image references
recorded in `deploy/production/known-good-images.lock`; do not use the root
`docker-compose.yml` for recovery because it can contain unreleased upgrades.

## Install the recovery services

After a reviewed deployment to `/root/projects/ssf-backend`, install the unit
files and enable automatic recovery and verification:

```bash
sudo ./scripts/install-production-systemd.sh
sudo systemctl start ssf-production.service
sudo systemctl start ssf-production-health.timer
sudo systemctl start ssf-backup-daily.timer ssf-backup-weekly.timer ssf-backup-monthly.timer
```

`ssf-production.service` only starts locally available pinned images
(`--pull never`, `--no-build`) and then applies the five-minute health gate.
It must be enabled only after the controlled activation procedure below.

## Verify recovery

```bash
sudo systemctl start ssf-production.service
sudo systemctl status ssf-production.service --no-pager
./scripts/production-health-check.sh --timeout-seconds 300
systemctl list-timers 'ssf-*' --all
```

The workload is healthy only when the health command succeeds. It covers the
GPU, all expected containers, API pipeline, Prometheus, Grafana, Keycloak,
Redis, and ClickHouse.

## Backups

Daily, weekly, and monthly timers create complete local backups under
`backups/<tier>/<UTC timestamp>`. Retention is seven daily, four weekly, and
twelve monthly backups. Every backup contains the stateful production Docker
audio volume, a logical Keycloak PostgreSQL export, Redis snapshot, ClickHouse
native backup, configuration and state directories, checksum manifests, and
archive readability validation. The database and Prometheus raw volumes are
intentionally not archived because they are actively written and their
consistent native snapshots are the recovery source. `ollama-models.txt`
records the installed model identifiers; after recovery, pull those models
again from the configured Ollama registry. This keeps recurring backups small
while retaining the information needed to restore the service configuration.
The Grafana SQLite database is captured separately using a consistent SQLite
snapshot. Loki log chunks and Promtail read positions are intentionally not
backed up: they change continuously and are not required to restore the
application or monitoring configuration.

To restore Grafana state, stop Grafana, replace
`monitoring/grafana/grafana.db` with the backup's `grafana.db`, remove any
stale `grafana.db-wal` and `grafana.db-shm` files, then start Grafana again.
Do not restore Loki history or Promtail positions.
The monthly job also restores the ClickHouse native backup into a temporary,
network-isolated ClickHouse container and fails if that drill cannot complete.
The backup directory stores `.env` with mode `0600` and the Git revision needed
for recovery; local backup access must therefore be restricted to operators.

Verify a concrete timestamp directory, never the `latest` symlink:

```bash
./scripts/verify-production-backup.sh backups/daily/20260830_001500
```

Backups are deliberately local only. They protect against accidental deletion,
failed updates, and single-volume corruption; they do not protect against loss
of the host or its storage.

## Controlled activation or rollback

Before activating a new canonical definition, run:

```bash
docker compose --env-file .env -f deploy/production/docker-compose.production.yml config --quiet
./scripts/production-health-check.sh --timeout-seconds 300
```

Make a verified backup first. Start the canonical workload with the systemd
unit, then run the health gate. If it does not pass within five minutes, stop
the unit and restore the last known-good container set and backup data; do not
pull images or use the mutable root Compose definition while investigating.

## Operating-system updates

Create and verify a concrete backup first, then run the preflight:

```bash
./scripts/prepare-os-update.sh
sudo apt-get -y upgrade
sudo reboot
./scripts/verify-os-update.sh
```

After any kernel or NVIDIA package update, the post-update check requires
`nvidia-smi -L` and the production health gate. If the NVIDIA driver is
unavailable, install the matching signed/open NVIDIA kernel module for the
running kernel before starting GPU workloads. Application image changes are a
separate controlled deployment: update the image lock and canonical Compose
file in review, verify locally, create a backup, then activate it and use the
five-minute health gate. Never combine application image upgrades with an OS
update.
