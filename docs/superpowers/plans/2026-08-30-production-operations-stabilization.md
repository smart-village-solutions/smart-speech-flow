# Production Operations Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use \`superpowers:executing-plans\` to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Make the production workload reproducible, automatically recoverable within five minutes of a reboot, and protected by verified daily local backups.

**Architecture:** A canonical pinned Compose definition will represent the known-good workload. systemd will start that definition only after Docker and NVIDIA readiness and then run a bounded health gate. Backup and health scripts will expose small, testable interfaces and use systemd timers.

**Tech Stack:** Docker Compose v5, systemd, Bash, GNU tar, PostgreSQL client tools, Redis CLI, ClickHouse client, NVIDIA tooling, Prometheus/Grafana.

**Spec:** \`openspec/changes/stabilize-production-operations/specs/production-operations/spec.md\`; \`docs/superpowers/specs/2026-08-30-production-operations-design.md\`

## Global Constraints

- The canonical definition includes every production service and pins every external image to a fixed version or digest; \`latest\` is forbidden.
- Its initial image set matches the known-good live workload and does not upgrade applications.
- Recovery verifies all required services within five minutes.
- At least one complete, verified local backup exists every 24 hours.
- Retention is seven daily, four weekly, and twelve monthly backups.
- Backups remain local; host-loss recovery is out of scope.
- Recovery and ordinary Compose commands never pull or replace images implicitly.

---

## File Structure

- \`deploy/production/docker-compose.production.yml\` — canonical pinned production topology.
- \`deploy/production/production.env.example\` — non-secret environment template.
- \`deploy/production/known-good-images.lock\` — current live image names, IDs, and immutable references.
- \`scripts/lib/production-common.sh\` — shared constants and command wrappers.
- \`scripts/production-health-check.sh\` — bounded platform and endpoint health gate.
- \`scripts/backup-production.sh\` and \`scripts/verify-production-backup.sh\` — complete backup and manifest verifier.
- \`scripts/restore-production-drill.sh\` — isolated monthly restore drill.
- \`scripts/prepare-os-update.sh\` and \`scripts/verify-os-update.sh\` — OS-update safety gates.
- \`deploy/systemd/*.service\` and \`deploy/systemd/*.timer\` — recovery and backup timers.
- \`tests/operations/test_production_compose.py\` and \`tests/operations/test_production_scripts.py\` — configuration and shell-contract tests.
- \`docs/operations/production-recovery.md\` — recovery and rollback runbook.

## Initial Live Image Inventory

Pin this known-good workload before any runtime replacement:

| Service | Initial reference |
| --- | --- |
| Redis | current \`redis:7-alpine\` digest |
| Ollama | \`ollama/ollama:0.32.0\` |
| Loki | \`grafana/loki:2.9.3\` |
| cAdvisor | \`gcr.io/cadvisor/cadvisor:v0.47.0\` |
| ClickHouse | \`clickhouse/clickhouse-server:26.3.17.110\` |
| DCGM exporter | current \`nvidia/dcgm-exporter:latest\` digest |
| Grafana | \`grafana/grafana:10.2.3\` |
| Node exporter | \`prom/node-exporter:v1.8.1\` |
| Prometheus | current locally cached image digest |
| Promtail | \`grafana/promtail:2.9.3\` |
| Traefik | current \`traefik:v2.11\` digest |
| Keycloak | \`ssf-keycloak:26.7.2\` |
| Keycloak PostgreSQL | \`postgres:17.7-alpine\` |
| Locally built services | current image IDs tagged as \`prod-<git-sha>\` |

### Task 1: Construct and validate the canonical production definition

**Files:**
- Create: \`deploy/production/docker-compose.production.yml\`
- Create: \`deploy/production/production.env.example\`
- Create: \`deploy/production/known-good-images.lock\`
- Create: \`tests/operations/test_production_compose.py\`
- Modify: \`.gitignore\`

**Interfaces:**
- Produces: \`docker compose --env-file /root/projects/ssf-backend/.env -f deploy/production/docker-compose.production.yml config --quiet\`.

- [ ] **Step 1: Write the failing Compose contract tests**

\`\`\`python
from pathlib import Path
import yaml


def load_production_compose():
    return yaml.safe_load(
        Path("deploy/production/docker-compose.production.yml").read_text()
    )


def test_production_compose_contains_required_services():
    services = load_production_compose()["services"]
    required = {
        "api_gateway", "asr", "translation", "tts", "ollama", "redis",
        "clickhouse", "keycloak", "keycloak-postgres", "traefik",
        "prometheus", "grafana", "loki", "promtail", "dcgm_exporter",
    }
    assert required.issubset(services)


def test_production_compose_forbids_mutable_image_tags():
    images = [
        service.get("image", "")
        for service in load_production_compose()["services"].values()
    ]
    assert all(":latest" not in image for image in images)
\`\`\`

- [ ] **Step 2: Run the contract tests and verify RED**

Run: \`pytest tests/operations/test_production_compose.py -v\`

Expected: FAIL because the canonical Compose file does not yet exist.

- [ ] **Step 3: Capture known-good immutable references**

Run:

\`\`\`bash
mkdir -p deploy/production
docker ps --filter label=com.docker.compose.project=ssf-backend \
  --format '{{.Names}} {{.Image}}' | sort > /tmp/ssf-live-images.txt
while read -r name image; do
  digest=$(docker image inspect --format '{{index .RepoDigests 0}}' "$image" 2>/dev/null || true)
  printf '%s\t%s\t%s\n' "$name" "$image" "$digest"
done < /tmp/ssf-live-images.txt > deploy/production/known-good-images.lock
\`\`\`

For locally built images, create immutable \`prod-<git-sha>\` tags before
referencing them. Do not use the newer image tags from the current root Compose
file in this migration.

- [ ] **Step 4: Implement the production topology**

Merge the root Compose topology and the Keycloak worktree topology into one
canonical file. Preserve every current named volume, the anonymous Prometheus
volume, models, TLS certificates, Grafana state, Loki state, Promtail state,
GPU reservations, health checks, ports, networks, and environment references.
Replace all external image tags with the recorded digest. Replace build stanzas
with immutable local production tags. Set \`restart: unless-stopped\` for every
long-running service, including ASR, translation, TTS, and Prometheus.

Keep only this template in Git:

\`\`\`dotenv
KEYCLOAK_DB_NAME=change-me
KEYCLOAK_DB_USER=change-me
KEYCLOAK_DB_PASSWORD=change-me
GRAFANA_ADMIN_PASSWORD=change-me
\`\`\`

- [ ] **Step 5: Verify GREEN without touching live containers**

Run:

\`\`\`bash
pytest tests/operations/test_production_compose.py -v
docker compose --env-file /root/projects/ssf-backend/.env \
  -f deploy/production/docker-compose.production.yml config --quiet
\`\`\`

Expected: tests PASS and Compose exits 0 without pulling, creating, or replacing containers.

- [ ] **Step 6: Commit**

\`\`\`bash
git add deploy/production tests/operations/test_production_compose.py .gitignore
git commit -m "feat(ops): add pinned production compose definition"
\`\`\`

### Task 2: Add the five-minute production health gate

**Files:**
- Create: \`scripts/lib/production-common.sh\`
- Create: \`scripts/production-health-check.sh\`
- Create: \`tests/operations/test_production_scripts.py\`

**Interfaces:**
- Consumes: \`SSF_PROJECT_ROOT\`, \`SSF_COMPOSE_FILE\`, and \`SSF_TIMEOUT_SECONDS\`.
- Produces: \`scripts/production-health-check.sh --timeout-seconds 300\`; exit 0 only when all checks pass.

- [ ] **Step 1: Write failing health-script tests**

\`\`\`python
def test_health_script_rejects_invalid_timeout(run_script):
    result = run_script(
        "scripts/production-health-check.sh", "--timeout-seconds", "zero"
    )
    assert result.returncode == 2
    assert "positive integer" in result.stderr


def test_health_script_reports_missing_gpu(run_script, stub_commands):
    stub_commands["nvidia-smi"] = (1, "", "driver unavailable")
    result = run_script(
        "scripts/production-health-check.sh", "--timeout-seconds", "1"
    )
    assert result.returncode == 1
    assert "GPU" in result.stderr
\`\`\`

- [ ] **Step 2: Verify RED**

Run: \`pytest tests/operations/test_production_scripts.py -k health -v\`

Expected: FAIL because the health script is missing.

- [ ] **Step 3: Implement explicit checks**

Implement \`run_check name command...\` in \`production-common.sh\`. The health
script validates, in order: \`nvidia-smi\`; expected canonical containers are
running; API \`http://127.0.0.1:8000/health\` returns ASR, Translation, and TTS
as \`ok\`; Prometheus internal \`/-/healthy\`; Grafana \`/api/health\`;
Keycloak health; \`redis-cli ping\`; and \`clickhouse-client --query 'SELECT 1'\`.
Poll every two seconds until the deadline and report each failed component to
stderr.

- [ ] **Step 4: Verify GREEN**

Run:

\`\`\`bash
pytest tests/operations/test_production_scripts.py -k health -v
scripts/production-health-check.sh --timeout-seconds 300
\`\`\`

Expected: tests and live health gate exit 0.

- [ ] **Step 5: Commit**

\`\`\`bash
git add scripts/lib/production-common.sh scripts/production-health-check.sh \
  tests/operations/test_production_scripts.py
git commit -m "feat(ops): add production health gate"
\`\`\`

### Task 3: Implement complete manifest-verified backups

**Files:**
- Create: \`scripts/backup-production.sh\`
- Create: \`scripts/verify-production-backup.sh\`
- Create: \`scripts/restore-production-drill.sh\`
- Modify: \`scripts/backup-common.sh\`, \`scripts/backup-daily.sh\`, \`scripts/backup-weekly.sh\`, \`scripts/backup-monthly.sh\`, \`scripts/verify-backups.sh\`
- Modify: \`tests/operations/test_production_scripts.py\`
- Modify: \`docs/deployment/BACKUP_STRATEGY.md\`

**Interfaces:**
- Produces: \`<backup-dir>/manifest.json\`, \`<backup-dir>/manifest.sha256\`, and \`scripts/verify-production-backup.sh <backup-dir>\`.

- [ ] **Step 1: Write failing manifest tests**

\`\`\`python
def test_backup_verifier_rejects_missing_required_artifact(run_script, tmp_path):
    backup = tmp_path / "backup"
    backup.mkdir()
    (backup / "manifest.json").write_text(
        '{"required": ["postgres.sql.gz"]}'
    )
    result = run_script("scripts/verify-production-backup.sh", str(backup))
    assert result.returncode == 1
    assert "postgres.sql.gz" in result.stderr


def test_backup_verifier_does_not_use_latest_symlink(run_script, tmp_path):
    backup = tmp_path / "backup"
    backup.mkdir()
    result = run_script("scripts/verify-production-backup.sh", str(backup))
    assert "latest" not in result.stderr.lower()
\`\`\`

- [ ] **Step 2: Verify RED**

Run: \`pytest tests/operations/test_production_scripts.py -k backup -v\`

Expected: FAIL because the manifest verifier is missing.

- [ ] **Step 3: Implement complete backup behavior**

Implement \`backup-production.sh --tier daily|weekly|monthly\` with \`flock\`.
Each run creates a new timestamp directory and captures:

1. a logical Keycloak PostgreSQL dump with \`pg_dump\`;
2. a Redis RDB after waiting for \`BGSAVE\`;
3. a ClickHouse native backup or logical export appropriate to the configured database;
4. all named project volumes: audio, ClickHouse, Keycloak PostgreSQL, Ollama, and Redis;
5. the anonymous Prometheus volume;
6. bind-mounted durable state: TLS certificates, Grafana data/provisioning, Loki data, Promtail data, monitoring configuration, and models;
7. canonical Compose, image lock, Git revision, and restricted secret-backup metadata.

Write the artifact list to \`manifest.json\`, calculate SHA-256 values in
\`manifest.sha256\`, and use the verifier as the last backup operation. The
verifier takes an explicit directory, requires every manifest item to exist and
be non-empty, runs \`tar -tzf\` on every archive, checks checksums, and never
uses a \`latest\` symlink.

- [ ] **Step 4: Implement retention and restore drill**

Keep seven daily, four weekly, and twelve monthly directories by tier. Route
the existing tier scripts to the new implementation. The monthly timer invokes
\`restore-production-drill.sh\`, which restores only to containers and paths
prefixed \`ssf-restore-drill-\`, then removes those isolated drill targets.

- [ ] **Step 5: Verify GREEN in an isolated destination**

Run:

\`\`\`bash
pytest tests/operations/test_production_scripts.py -k backup -v
export SSF_BACKUP_ROOT=$(mktemp -d)
scripts/backup-production.sh --tier daily
backup_dir=$(find "$SSF_BACKUP_ROOT/daily" -mindepth 1 -maxdepth 1 -type d | head -1)
scripts/verify-production-backup.sh "$backup_dir"
\`\`\`

Expected: tests PASS and every manifest artifact verifies.

- [ ] **Step 6: Commit**

\`\`\`bash
git add scripts tests/operations/test_production_scripts.py \
  docs/deployment/BACKUP_STRATEGY.md
git commit -m "feat(ops): add verified production backups"
\`\`\`

### Task 4: Add systemd recovery and backup scheduling

**Files:**
- Create: \`deploy/systemd/ssf-production.service\`
- Create: \`deploy/systemd/ssf-backup-daily.service\`, \`deploy/systemd/ssf-backup-daily.timer\`
- Create: \`deploy/systemd/ssf-backup-weekly.service\`, \`deploy/systemd/ssf-backup-weekly.timer\`
- Create: \`deploy/systemd/ssf-backup-monthly.service\`, \`deploy/systemd/ssf-backup-monthly.timer\`
- Create: \`scripts/install-production-systemd.sh\`
- Modify: \`tests/operations/test_production_scripts.py\`

**Interfaces:**
- Produces: enabled \`ssf-production.service\` and the three backup timers.

- [ ] **Step 1: Write failing unit-file tests**

\`\`\`python
from pathlib import Path


def test_production_unit_waits_for_docker_and_nvidia():
    text = Path("deploy/systemd/ssf-production.service").read_text()
    assert "After=docker.service nvidia-persistenced.service" in text
    assert "production-health-check.sh --timeout-seconds 300" in text


def test_daily_timer_runs_every_day():
    text = Path("deploy/systemd/ssf-backup-daily.timer").read_text()
    assert "OnCalendar=daily" in text
    assert "Persistent=true" in text
\`\`\`

- [ ] **Step 2: Verify RED**

Run: \`pytest tests/operations/test_production_scripts.py -k systemd -v\`

Expected: FAIL because the unit files are missing.

- [ ] **Step 3: Implement safe units and installer**

The production unit has \`Requires=docker.service\`,
\`After=docker.service nvidia-persistenced.service\`, and
\`RemainAfterExit=yes\`. Its start command runs canonical Compose
\`up -d --no-build --no-recreate\`; its post-start runs the 300-second health
gate; its stop command must never use \`down -v\`. Timers use
\`OnCalendar=daily\`, \`Sun *-*-* 01:00:00\`, and \`*-*-01 02:00:00\` with
\`Persistent=true\` and \`RandomizedDelaySec=10m\`.

The installer copies only named unit files to \`/etc/systemd/system\`, runs
\`systemctl daemon-reload\`, enables the timers and production unit, and prints
status without invoking an unreviewed Compose replacement.

- [ ] **Step 4: Verify GREEN**

Run:

\`\`\`bash
pytest tests/operations/test_production_scripts.py -k systemd -v
systemd-analyze verify deploy/systemd/*.service deploy/systemd/*.timer
shellcheck scripts/install-production-systemd.sh \
  scripts/production-health-check.sh scripts/backup-production.sh \
  scripts/verify-production-backup.sh
\`\`\`

Expected: all commands exit 0.

- [ ] **Step 5: Commit**

\`\`\`bash
git add deploy/systemd scripts/install-production-systemd.sh \
  tests/operations/test_production_scripts.py
git commit -m "feat(ops): add reboot recovery and backup timers"
\`\`\`

### Task 5: Add controlled update and rollback operations

**Files:**
- Create: \`scripts/prepare-os-update.sh\`
- Create: \`scripts/verify-os-update.sh\`
- Create: \`docs/operations/production-recovery.md\`
- Modify: \`docs/operations/deployment-rollback-procedure.md\`
- Modify: \`tests/operations/test_production_scripts.py\`

**Interfaces:**
- Produces: OS-update preflight and verification commands plus a canonical Compose rollback procedure.

- [ ] **Step 1: Write failing update guard tests**

\`\`\`python
def test_os_update_preflight_runs_simulation_and_backup(run_script, stub_commands):
    result = run_script("scripts/prepare-os-update.sh")
    assert result.returncode == 0
    assert stub_commands.calls == [
        ["apt-get", "-s", "upgrade"],
        ["scripts/backup-production.sh", "--tier", "daily"],
    ]


def test_os_update_verifier_delegates_to_health_gate(run_script, stub_commands):
    result = run_script("scripts/verify-os-update.sh")
    assert result.returncode == 0
    assert ["scripts/production-health-check.sh", "--timeout-seconds", "300"] in stub_commands.calls
\`\`\`

- [ ] **Step 2: Verify RED**

Run: \`pytest tests/operations/test_production_scripts.py -k update -v\`

Expected: FAIL because the scripts are missing.

- [ ] **Step 3: Implement controlled operation scripts and runbook**

\`prepare-os-update.sh\` runs \`apt-get -s upgrade\`, creates and verifies a
fresh daily backup, then prints the reboot command without executing it.
\`verify-os-update.sh\` confirms no upgradable packages remain, runs
\`nvidia-smi\`, and invokes the health gate.

Update the rollback runbook to select a previously committed canonical Compose
definition and lock file, run Compose config validation, use targeted
\`up -d --no-deps --no-build <service>\`, and rerun health verification.
Explicitly prohibit unpinned images, \`docker compose down -v\`, and
\`git reset --hard\` on production.

- [ ] **Step 4: Verify GREEN**

Run:

\`\`\`bash
pytest tests/operations/test_production_scripts.py -k update -v
rg -n 'docker-compose.production.yml|production-health-check.sh|down -v' \
  docs/operations/production-recovery.md \
  docs/operations/deployment-rollback-procedure.md
\`\`\`

Expected: tests PASS and runbooks name the canonical recovery path.

- [ ] **Step 5: Commit**

\`\`\`bash
git add scripts/prepare-os-update.sh scripts/verify-os-update.sh \
  docs/operations/production-recovery.md \
  docs/operations/deployment-rollback-procedure.md \
  tests/operations/test_production_scripts.py
git commit -m "docs(ops): define controlled update and rollback flow"
\`\`\`

### Task 6: Activate, test reboot recovery, and remove stale artifacts

**Files:**
- Modify: \`docs/operations/production-recovery.md\`
- Modify: \`openspec/changes/stabilize-production-operations/tasks.md\`

**Interfaces:**
- Consumes: validated canonical definition, enabled units, verified backup, and health gate.
- Produces: measured five-minute recovery evidence and a clean container inventory.

- [ ] **Step 1: Capture final baseline**

Run:

\`\`\`bash
scripts/production-health-check.sh --timeout-seconds 300
scripts/backup-production.sh --tier daily
backup_dir=$(find /root/projects/ssf-backend/backups/daily -mindepth 1 -maxdepth 1 -type d | sort | tail -1)
scripts/verify-production-backup.sh "$backup_dir"
\`\`\`

Expected: both health and backup verification exit 0.

- [ ] **Step 2: Install and enable the reviewed units**

Run:

\`\`\`bash
sudo scripts/install-production-systemd.sh
systemctl status --no-pager ssf-production.service \
  ssf-backup-daily.timer ssf-backup-weekly.timer ssf-backup-monthly.timer
\`\`\`

Expected: all units are loaded and no application image is replaced.

- [ ] **Step 3: Perform the controlled reboot test**

Run:

\`\`\`bash
sudo systemctl reboot
# After SSH reconnects:
systemctl status --no-pager ssf-production.service
scripts/production-health-check.sh --timeout-seconds 300
\`\`\`

Expected: all services recover within five minutes. On failure, restore the
previous production-unit and Compose commit; do not remove a volume.

- [ ] **Step 4: Remove only verified orphan containers**

Before deletion, prove each candidate is unstarted and unused:

\`\`\`bash
docker inspect --format '{{.State.Status}} {{.State.StartedAt}}' \
  5a9d4d6a1a80 982327844a57 3dbb25634a3f
\`\`\`

Expected: every candidate is \`created\` with a zero \`StartedAt\`. Then run:

\`\`\`bash
docker rm 5a9d4d6a1a80 982327844a57 3dbb25634a3f
\`\`\`

- [ ] **Step 5: Record verification evidence and commit**

Record measured recovery time, health summary, backup location, and restore
drill result in the runbook. Check OpenSpec tasks only when the documented
evidence exists.

\`\`\`bash
git add docs/operations/production-recovery.md \
  openspec/changes/stabilize-production-operations/tasks.md
git commit -m "chore(ops): verify production recovery"
\`\`\`

## Final Verification

- [ ] \`docker compose --env-file /root/projects/ssf-backend/.env -f deploy/production/docker-compose.production.yml config --quiet\`
- [ ] \`pytest tests/operations/test_production_compose.py tests/operations/test_production_scripts.py -v\`
- [ ] \`systemd-analyze verify deploy/systemd/*.service deploy/systemd/*.timer\`
- [ ] Fresh \`scripts/verify-production-backup.sh <backup-dir>\`
- [ ] Controlled reboot followed by \`scripts/production-health-check.sh --timeout-seconds 300\`
- [ ] \`openspec validate stabilize-production-operations --strict\`
