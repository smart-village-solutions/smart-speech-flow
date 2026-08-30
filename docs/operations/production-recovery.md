# Production recovery and backup runbook

The production workload is defined only by
`deploy/production/docker-compose.production.yml`. It uses the image references
recorded in `deploy/production/known-good-images.lock`; do not use the root
`docker-compose.yml` for recovery because it can contain unreleased upgrades.

## Install the recovery services

After a reviewed deployment to `/root/projects/ssf-backend`, install the unit
files and enable automatic recovery and verification:

```bash
sudo install -m 0644 deploy/systemd/ssf-*.service deploy/systemd/ssf-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ssf-production.service ssf-production-health.timer
sudo systemctl enable --now ssf-backup-daily.timer ssf-backup-weekly.timer ssf-backup-monthly.timer
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
twelve monthly backups. Every backup contains all production Docker volumes,
a logical Keycloak PostgreSQL export, Redis snapshot, configuration and state
directories, checksum manifests, and archive readability validation.

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
./scripts/prepare-os-update.sh backups/daily/20260830_001500
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
