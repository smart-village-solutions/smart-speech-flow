# ClickHouse Infrastructure and Telemetry Proposal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a secure, internal ClickHouse service on the SSF Docker Compose host, document its operation, and publish an OpenSpec proposal and linked GitHub issue for a colleague to implement quality telemetry later.

**Architecture:** ClickHouse is an internal, persistent analytical service with no host port or Traefik route. It holds only pseudonymised KPI metadata. Consent-governed texts and audio remain out of scope for ClickHouse and must use a separate transactional content store and encrypted object store in a later capability.

**Tech Stack:** Docker Compose, ClickHouse Server, pytest, OpenSpec, GitHub CLI or authenticated GitHub connector.

**Spec:** `docs/superpowers/specs/2026-08-25-clickhouse-telemetry-design.md`

## Global Constraints

- Pin the ClickHouse image to a specific stable or LTS release; do not use `latest`.
- Expose no ClickHouse host port and add no Traefik label or public SQL UI.
- Require a non-empty `CLICKHOUSE_PASSWORD` from `.env`; do not use insecure setup bypasses.
- Store telemetry metadata only; never write content, IP addresses, or free-form errors to ClickHouse.
- Keep all new or modified project documentation in English.
- Do not implement the API Gateway telemetry writer in this plan.

---

### Task 1: Add an executable Compose-security contract

**Files:**
- Create: `tests/test_clickhouse_compose_configuration.py`
- Modify: `docker-compose.yml`

**Interfaces:**
- Consumes: the resolved Compose configuration emitted by `docker compose config` with an isolated test environment.
- Produces: `test_clickhouse_service_is_internal_and_persistent()` and `test_clickhouse_service_requires_credentials()` as regression checks for the deployment contract.

- [ ] **Step 1: Write the failing tests**

```python
import os
import subprocess
import tempfile
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


def _clickhouse_service():
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as env_file:
        env_file.write("CLICKHOUSE_DB=ssf_analytics_test\n")
        env_file.write("CLICKHOUSE_USER=ssf_telemetry_test\n")
        env_file.write("CLICKHOUSE_PASSWORD=test-only-password\n")
    try:
        result = subprocess.run(
            ["docker", "compose", "--env-file", env_file.name, "config"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        os.unlink(env_file.name)
    return yaml.safe_load(result.stdout)["services"]["clickhouse"]


def test_clickhouse_service_is_internal_and_persistent():
    service = _clickhouse_service()
    assert service["image"].startswith("clickhouse/clickhouse-server:")
    assert service["restart"] == "always"
    assert service.get("ports") is None
    assert service["expose"] == ["8123"]
    assert "clickhouse-data:/var/lib/clickhouse" in service["volumes"]
    assert service.get("labels") is None


def test_clickhouse_service_requires_credentials():
    environment = _clickhouse_service()["environment"]
    assert environment["CLICKHOUSE_PASSWORD"] == "test-only-password"
    assert environment["CLICKHOUSE_USER"] == "ssf_telemetry_test"
    assert environment["CLICKHOUSE_DB"] == "ssf_analytics_test"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_clickhouse_compose_configuration.py -v`

Expected: FAIL because the `clickhouse` service does not yet exist.

- [ ] **Step 3: Add the minimal Compose service**

Add the service alongside the internal database/monitoring services:

```yaml
  clickhouse:
    image: clickhouse/clickhouse-server:26.3.17.110
    restart: always
    expose:
      - "8123"
    environment:
      - CLICKHOUSE_DB=${CLICKHOUSE_DB:?set CLICKHOUSE_DB in .env}
      - CLICKHOUSE_USER=${CLICKHOUSE_USER:?set CLICKHOUSE_USER in .env}
      - CLICKHOUSE_PASSWORD=${CLICKHOUSE_PASSWORD:?set CLICKHOUSE_PASSWORD in .env}
      - CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT=1
    ulimits:
      nofile:
        soft: 262144
        hard: 262144
    volumes:
      - clickhouse-data:/var/lib/clickhouse
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:8123/ping | grep -qx 'Ok.'"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 30s
```

Add `clickhouse-data:` under the existing top-level `volumes:`. `26.3.17.110` is the currently published LTS version; record the selected version and review it during every upgrade rather than using a floating tag.

- [ ] **Step 4: Run the focused tests and Compose validation**

Run:

```bash
pytest tests/test_clickhouse_compose_configuration.py -v
docker compose --env-file .env.example config --quiet
```

Expected: the tests PASS and the second command succeeds after test-only placeholder credentials are supplied through an isolated temporary env file, never through production `.env`.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml tests/test_clickhouse_compose_configuration.py
git commit -m "feat: add internal ClickHouse service"
```

### Task 2: Document credentials, security posture, and operator workflow

**Files:**
- Modify: `.env.example`
- Modify: `docs/deployment/SECURITY.md`
- Create: `docs/operations/runbooks/clickhouse-operations.md`
- Modify: `docs/README.md`

**Interfaces:**
- Consumes: the `clickhouse` Compose service from Task 1 and `.env` values.
- Produces: a self-contained operator runbook whose commands use only internal container access.

- [ ] **Step 1: Write the failing documentation acceptance checklist**

Create the checklist before editing documentation and verify every item manually after edits:

```text
[ ] .env.example lists CLICKHOUSE_DB, CLICKHOUSE_USER, and CLICKHOUSE_PASSWORD without a real value.
[ ] SECURITY.md states that ClickHouse has no host port and must not receive Traefik labels.
[ ] The runbook includes first start, health, authenticated query, logs, upgrade, rollback, backup, restore, and incident commands.
[ ] docs/README.md links the runbook under operator documentation.
[ ] No command prints a secret or recommends CLICKHOUSE_SKIP_USER_SETUP.
```

- [ ] **Step 2: Verify the checklist fails before documentation changes**

Run: `rg -n "CLICKHOUSE_|clickhouse-operations" .env.example docs/deployment/SECURITY.md docs/README.md`

Expected: no ClickHouse configuration or operator-runbook link is present.

- [ ] **Step 3: Add documentation and configuration placeholders**

Add to `.env.example`:

```dotenv
# Internal ClickHouse analytics service
CLICKHOUSE_DB=ssf_analytics
CLICKHOUSE_USER=ssf_telemetry
CLICKHOUSE_PASSWORD=replace_with_a_unique_strong_password
```

Document a production password generation command (`openssl rand -base64 32`) without adding credentials to any tracked file. The runbook must include these commands:

```bash
docker compose up -d clickhouse
docker compose ps clickhouse
docker compose exec clickhouse clickhouse-client \
  --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" \
  --query 'SELECT version()'
docker compose logs --tail=100 clickhouse
```

Document a logical backup with `clickhouse-client` format export, a restore into a temporary database, and a rollback that preserves `clickhouse-data`. State clearly that no current table is created by the infrastructure task; the future telemetry change creates its own schema.

- [ ] **Step 4: Verify the documentation acceptance checklist**

Run:

```bash
rg -n "CLICKHOUSE_(DB|USER|PASSWORD)|clickhouse-operations" .env.example docs/deployment/SECURITY.md docs/README.md
rg -n "CLICKHOUSE_SKIP_USER_SETUP|ports:|traefik" docs/operations/runbooks/clickhouse-operations.md
```

Expected: required references are present; the runbook contains no insecure setup command and explicitly prohibits external ports and Traefik labels.

- [ ] **Step 5: Commit**

```bash
git add .env.example docs/deployment/SECURITY.md docs/operations/runbooks/clickhouse-operations.md docs/README.md
git commit -m "docs: add ClickHouse operations runbook"
```

### Task 3: Validate the installed service without affecting existing SSF services

**Files:**
- Modify: `docs/operations/runbooks/clickhouse-operations.md` only if validation reveals an inaccurate command.

**Interfaces:**
- Consumes: the service, credentials configured locally in untracked `.env`, and named volume from Task 1.
- Produces: verified evidence that internal authenticated queries work and data persists across container recreation.

- [ ] **Step 1: Start only ClickHouse**

Run: `docker compose up -d clickhouse`

Expected: only the ClickHouse container is created or started; no application service is recreated.

- [ ] **Step 2: Verify internal health and authentication**

Run:

```bash
docker compose exec clickhouse wget -qO- http://localhost:8123/ping
docker compose exec clickhouse clickhouse-client \
  --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" \
  --query 'SELECT version()'
```

Expected: `/ping` returns `Ok.` and the query prints a version. Do not include the password in terminal output, logs, commits, or issue text.

- [ ] **Step 3: Verify no host exposure and persistence**

Run:

```bash
docker inspect "$(docker compose ps -q clickhouse)" --format '{{json .HostConfig.PortBindings}}'
docker compose exec clickhouse clickhouse-client \
  --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" \
  --query 'CREATE TABLE IF NOT EXISTS ssf_install_check (id UInt8) ENGINE = MergeTree ORDER BY id'
docker compose exec clickhouse clickhouse-client \
  --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" \
  --query 'INSERT INTO ssf_install_check VALUES (1)'
docker compose up -d --force-recreate clickhouse
until docker compose exec -T clickhouse wget -qO- http://localhost:8123/ping | grep -qx 'Ok.'; do sleep 3; done
docker compose ps clickhouse
docker compose exec clickhouse clickhouse-client \
  --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" \
  --query 'SELECT count() FROM ssf_install_check'
docker compose exec clickhouse clickhouse-client \
  --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" \
  --query 'DROP TABLE ssf_install_check'
```

Expected: Docker inspection returns `{}` for host port bindings; the container returns healthy; the post-recreation query returns `1`; and the temporary installation-check table is removed. This does not create a future telemetry schema.

- [ ] **Step 4: Run project checks**

Run:

```bash
docker compose config --quiet
pytest tests/test_clickhouse_compose_configuration.py -v
pytest
```

Expected: Compose configuration is valid; focused configuration tests and the full existing suite pass.

- [ ] **Step 5: Commit any validated runbook correction**

```bash
git add docs/operations/runbooks/clickhouse-operations.md
git commit -m "docs: verify ClickHouse operating procedure"
```

### Task 4: Create the OpenSpec change for future quality telemetry

**Files:**
- Create: `openspec/changes/add-clickhouse-quality-telemetry/proposal.md`
- Create: `openspec/changes/add-clickhouse-quality-telemetry/design.md`
- Create: `openspec/changes/add-clickhouse-quality-telemetry/tasks.md`
- Create: `openspec/changes/add-clickhouse-quality-telemetry/specs/quality-telemetry/spec.md`

**Interfaces:**
- Consumes: the approved design and KPI catalogue at `docs/operations/conversation-quality-kpis.en.md`.
- Produces: an unapproved implementation proposal for a colleague; no API Gateway code.

- [ ] **Step 1: Create proposal and design documents**

`proposal.md` must state why analytical quality telemetry is needed, list the ClickHouse event contract and writer as future changes, and explicitly exclude raw content and content-store implementation. `design.md` must define:

```text
event_id: UUID; delivery retries are idempotent
schema_version: integer; required on every event
writer behavior: bounded queue plus asynchronous batch/async inserts
failure behavior: record an operational counter/log without delaying or failing message processing
retention: raw metadata 30 days; pseudonymised daily aggregates 13 months
content boundary: only content_record_id_hash and consent metadata; no text/audio/content bytes
```

- [ ] **Step 2: Create a delta specification with scenarios**

Add requirements and scenarios that demonstrate:

```markdown
#### Scenario: ClickHouse is unavailable
- **WHEN** the telemetry writer cannot insert a batch
- **THEN** the message pipeline completes independently and the failed telemetry batch is observable without content leakage

#### Scenario: An event is retried
- **WHEN** the writer delivers the same `event_id` more than once
- **THEN** the analytical record is counted once

#### Scenario: Content-bearing metadata is received
- **WHEN** an event source includes text, an audio URL, raw error text, or bytes
- **THEN** the telemetry payload excludes it and retains only approved metadata
```

- [ ] **Step 3: Create implementation tasks for the colleague**

Sequence the tasks: schema and migrations; typed allowlisted event models; writer and retry/batching; gateway lifecycle/pipeline hooks; retention/aggregation; tests; dashboards/runbooks. Include the separate content-store capability as a dependency, not a task to implement in this change.

- [ ] **Step 4: Validate OpenSpec**

Run: `openspec validate add-clickhouse-quality-telemetry --strict`

Expected: validation succeeds with no formatting or scenario errors.

- [ ] **Step 5: Commit**

```bash
git add openspec/changes/add-clickhouse-quality-telemetry
git commit -m "docs: propose ClickHouse quality telemetry"
```

### Task 5: Create and link the GitHub implementation issue

**Files:**
- Modify: `openspec/changes/add-clickhouse-quality-telemetry/proposal.md` to include the created issue URL.

**Interfaces:**
- Consumes: validated OpenSpec proposal and authenticated GitHub access to `smart-village-solutions/smart-speech-flow`.
- Produces: one GitHub issue assigned or ready for the implementation colleague, linked bidirectionally to the OpenSpec change.

- [ ] **Step 1: Verify GitHub identity and repository access**

Run:

```bash
gh auth status
gh repo view smart-village-solutions/smart-speech-flow
```

Expected: the authenticated account can create issues. If GitHub access is not authenticated, stop and request that the user connect the GitHub integration or authenticate `gh`; do not fabricate an issue link.

- [ ] **Step 2: Create the issue from a reviewed body file**

Create an untracked temporary Markdown body containing the change path, acceptance criteria from the delta spec, privacy boundary, non-goals, and validation requirements. Then run:

```bash
gh issue create \
  --repo smart-village-solutions/smart-speech-flow \
  --title "feat: implement ClickHouse quality telemetry" \
  --body-file /tmp/clickhouse-quality-telemetry-issue.md
```

Expected: GitHub returns the canonical issue URL. Do not include credentials, pseudonymous production identifiers, or any content example in the issue.

- [ ] **Step 3: Add bidirectional references and validate**

Add a `GitHub issue:` line containing the canonical URL returned in Step 2 to the OpenSpec proposal. Add a comment to the issue linking the committed OpenSpec proposal path and commit SHA. Re-run:

```bash
openspec validate add-clickhouse-quality-telemetry --strict
git add openspec/changes/add-clickhouse-quality-telemetry/proposal.md
git commit -m "docs: link telemetry proposal to implementation issue"
```

- [ ] **Step 4: Final verification and handoff**

Run:

```bash
git status --short
git log --oneline --max-count=5
docker compose config --quiet
pytest tests/test_clickhouse_compose_configuration.py -v
openspec validate add-clickhouse-quality-telemetry --strict
```

Expected: working tree is clean; infrastructure validation and OpenSpec validation pass; handoff includes the issue URL, OpenSpec change ID, and explicit statement that API Gateway telemetry remains unimplemented.
