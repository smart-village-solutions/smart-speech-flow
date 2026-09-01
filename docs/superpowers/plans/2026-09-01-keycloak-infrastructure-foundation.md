# Keycloak Infrastructure Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a pinned Keycloak instance operational behind Traefik with a private, persistent PostgreSQL database, without enabling SSF authentication or Studio provisioning.

**Architecture:** Docker Compose runs an optimized Keycloak 26.7.2 image and a dedicated PostgreSQL 17.7-alpine database on the existing private Compose network. Traefik is the only public entry point; the deployment-specific `KEYCLOAK_HOSTNAME` configures both Keycloak's canonical URL and its TLS router. Python contract tests render Compose with throwaway values and protect this boundary.

**Tech Stack:** Docker Compose, Traefik, Keycloak 26.7.2, PostgreSQL 17.7-alpine, pytest, PyYAML.

**Spec:** `docs/superpowers/specs/2026-09-01-keycloak-infrastructure-design.md`

## Global Constraints

- Pin the Keycloak image and custom build to `26.7.2` and PostgreSQL to `17.7-alpine`.
- Require `KEYCLOAK_HOSTNAME`; production sets it to `auth.kassel.smartspeechflow.de`.
- Require `KEYCLOAK_DB_NAME`, `KEYCLOAK_DB_USER`, `KEYCLOAK_DB_PASSWORD`, `KEYCLOAK_BOOTSTRAP_ADMIN_USERNAME`, and `KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD` from the ignored deployment `.env` only.
- Do not publish a host port or Traefik route for Keycloak PostgreSQL or Keycloak management port `9000`.
- Do not add realm imports, clients, roles, claims, service accounts, Studio provisioning, gateway authorization, frontend login behaviour, or a Node toolchain migration.
- Keep all newly created or modified project documentation, commit messages, and PR material in English.

---

## File Structure

- `services/keycloak/Dockerfile` creates the optimized, pinned Keycloak runtime image.
- `docker-compose.yml` declares the private Keycloak database, the Keycloak service, health checks, persistent storage, and its parameterized Traefik route.
- `.env.example` documents all required, non-production Keycloak configuration keys.
- `tests/test_keycloak_compose_configuration.py` renders Compose and asserts the Keycloak security and configuration contract.
- `tests/test_clickhouse_compose_configuration.py` and `tests/test_frontend_container_build.py` provide every required Compose variable to their isolated Compose invocations.
- `docs/operations/runbooks/keycloak-operations.md`, `docs/deployment/BACKUP_STRATEGY.md`, `docs/deployment/SECURITY.md`, and `docs/README.md` provide deployment, recovery, security, and navigation guidance.

### Task 1: Rebase the isolated feature branch onto current main

**Files:**
- Modify: all files listed in the File Structure section only when a rebase conflict requires carrying the intended Keycloak change forward
- Test: `git diff --check`

**Interfaces:**
- Consumes: the existing `feat/keycloak-infrastructure` commits and uncommitted Keycloak infrastructure changes.
- Produces: a clean feature branch based on `origin/main` that retains the agreed Keycloak foundation scope.

- [ ] **Step 1: Capture the current worktree state in a local checkpoint commit**

Run:

```bash
git status --short
git add .env.example docker-compose.yml docs tests services/keycloak
git commit -m "feat: add Keycloak infrastructure foundation"
```

Expected: the Keycloak infrastructure files are represented by a local commit; unrelated files are not staged.

- [ ] **Step 2: Rebase the branch on the current remote main**

Run:

```bash
git fetch origin main
git rebase origin/main
```

Expected: `git merge-base HEAD origin/main` equals `git rev-parse origin/main` after any conflicts are resolved with the intended Keycloak-only diff.

- [ ] **Step 3: Verify the rebased diff contains no whitespace errors**

Run:

```bash
git diff origin/main...HEAD --check
git status --short
```

Expected: `git diff --check` is silent and the worktree is clean.

- [ ] **Step 4: Commit conflict resolutions if rebase required a follow-up change**

Run:

```bash
git add .
git commit -m "chore: rebase Keycloak infrastructure on main"
```

Expected: create this commit only when a post-rebase correction is necessary; otherwise do not create an empty commit.

### Task 2: Parameterize and secure the Compose topology

**Files:**
- Create: `services/keycloak/Dockerfile`
- Modify: `.env.example: Keycloak configuration section`
- Modify: `docker-compose.yml: services.keycloak-postgres, services.keycloak, volumes`
- Test: `tests/test_keycloak_compose_configuration.py`

**Interfaces:**
- Consumes: the six `KEYCLOAK_*` Compose environment variables from `.env`.
- Produces: `keycloak-postgres` and `keycloak` services; Keycloak exposes internal port `8080`, uses `KEYCLOAK_HOSTNAME`, and the database persists in `keycloak-postgres-data`.

- [ ] **Step 1: Write the failing hostname configuration test**

In `tests/test_keycloak_compose_configuration.py`, write the variable to the temporary env file and assert the rendered values:

```python
env_file.write("KEYCLOAK_HOSTNAME=auth.test.example\\n")

assert keycloak["labels"]["traefik.http.routers.keycloak.rule"] == "Host(\`auth.test.example\`)"
assert keycloak["environment"]["KC_HOSTNAME"] == "https://auth.test.example"
```

- [ ] **Step 2: Run the focused contract test to verify it fails**

Run:

```bash
pytest tests/test_keycloak_compose_configuration.py -q
```

Expected: FAIL because the Compose service still hard-codes the Kassel hostname or lacks `KEYCLOAK_HOSTNAME` in the test environment.

- [ ] **Step 3: Implement the minimal parameterized Compose configuration**

In `.env.example`, add the non-secret deployment key:

```dotenv
KEYCLOAK_HOSTNAME=auth.example.com
```

In `docker-compose.yml`, make both canonical hostname consumers use the same required value:

```yaml
KC_HOSTNAME: https://${KEYCLOAK_HOSTNAME:?required}
labels:
  - "traefik.http.routers.keycloak.rule=Host(\`${KEYCLOAK_HOSTNAME:?required}\`)"
```

Retain the existing private PostgreSQL configuration, `expose: ["8080"]`, container-local port-9000 readiness probe, persistent volume, and Traefik TLS labels. Do not add `ports` to either service.

- [ ] **Step 4: Run the focused test and Compose rendering check**

Run:

```bash
pytest tests/test_keycloak_compose_configuration.py -q
docker compose --env-file <(printf '%s\\n' 'CLICKHOUSE_DB=test' 'CLICKHOUSE_USER=test' 'CLICKHOUSE_PASSWORD=test' 'KEYCLOAK_HOSTNAME=auth.test.example' 'KEYCLOAK_DB_NAME=keycloak' 'KEYCLOAK_DB_USER=keycloak' 'KEYCLOAK_DB_PASSWORD=test' 'KEYCLOAK_BOOTSTRAP_ADMIN_USERNAME=admin' 'KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD=test') config --quiet
```

Expected: both commands exit successfully; the rendered configuration has no public database or management port.

- [ ] **Step 5: Commit the topology and contract-test change**

Run:

```bash
git add services/keycloak/Dockerfile docker-compose.yml .env.example tests/test_keycloak_compose_configuration.py
git commit -m "feat: deploy Keycloak behind Traefik"
```

Expected: one focused commit contains the Keycloak image, Compose topology, configuration key, and security-contract test.

### Task 3: Keep all existing Compose test entry points renderable

**Files:**
- Modify: `tests/test_clickhouse_compose_configuration.py: _clickhouse_service`
- Modify: `tests/test_frontend_container_build.py: _compose_build`
- Test: `tests/test_clickhouse_compose_configuration.py`, `tests/test_frontend_container_build.py`

**Interfaces:**
- Consumes: Compose's required `KEYCLOAK_HOSTNAME` and credential environment variables.
- Produces: existing test helpers that render/build the full Compose project without reading a real `.env` file.

- [ ] **Step 1: Add the required hostname variable to both helpers**

Add the same test-only hostname environment value to each helper:

```python
env_file.write("KEYCLOAK_HOSTNAME=auth.test.example\\n")
```

and:

```python
environment["KEYCLOAK_HOSTNAME"] = "auth.test.example"
```

- [ ] **Step 2: Run the affected tests before adapting the helpers**

Run:

```bash
pytest tests/test_clickhouse_compose_configuration.py tests/test_frontend_container_build.py -q
```

Expected: the Compose rendering path fails until every required Keycloak variable, including the hostname, is supplied.

- [ ] **Step 3: Provide all isolated Keycloak test values in both helpers**

Ensure both helpers set exactly these non-production values in addition to their existing ClickHouse values:

```text
KEYCLOAK_DB_NAME=keycloak_test
KEYCLOAK_DB_USER=keycloak_test_user
KEYCLOAK_DB_PASSWORD=test-only-db-password
KEYCLOAK_BOOTSTRAP_ADMIN_USERNAME=bootstrap_admin
KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD=test-only-admin-password
KEYCLOAK_HOSTNAME=auth.test.example
```

- [ ] **Step 4: Run the affected tests after adapting the helpers**

Run:

```bash
pytest tests/test_clickhouse_compose_configuration.py tests/test_frontend_container_build.py -q
```

Expected: PASS without depending on developer secrets or a local `.env` file.

- [ ] **Step 5: Commit the test-helper compatibility change**

Run:

```bash
git add tests/test_clickhouse_compose_configuration.py tests/test_frontend_container_build.py
git commit -m "test: supply Keycloak Compose variables"
```

Expected: one focused commit restores isolated rendering/build tests.

### Task 4: Document safe operations and verify the PR candidate

**Files:**
- Create: `docs/operations/runbooks/keycloak-operations.md`
- Modify: `docs/README.md: Operations runbooks list`
- Modify: `docs/deployment/BACKUP_STRATEGY.md: Keycloak identity data section`
- Modify: `docs/deployment/SECURITY.md: private-service table and credential checklist`
- Test: `tests/test_keycloak_compose_configuration.py`, `tests/test_clickhouse_compose_configuration.py`, `tests/test_frontend_container_build.py`

**Interfaces:**
- Consumes: the Compose service names `keycloak` and `keycloak-postgres`, plus `KEYCLOAK_HOSTNAME`.
- Produces: an operator runbook for DNS/TLS validation, startup, readiness verification, encrypted logical backups, restore verification, upgrade, rollback, and incident boundaries.

- [ ] **Step 1: Add documentation checks to the focused Keycloak contract test**

Add assertions that the runbook contains the parameterized hostname and private-port policy:

```python
runbook = (ROOT / "docs/operations/runbooks/keycloak-operations.md").read_text()
assert "KEYCLOAK_HOSTNAME" in runbook
assert "management port 9000" in runbook
```

- [ ] **Step 2: Run the focused Keycloak test to verify it fails before documentation exists**

Run:

```bash
pytest tests/test_keycloak_compose_configuration.py -q
```

Expected: FAIL until the referenced runbook uses the configured hostname and records the management-port boundary.

- [ ] **Step 3: Write the runbook and deployment documentation**

Document these executable, non-secret operations:

```bash
docker compose build keycloak
docker compose up -d keycloak-postgres keycloak
docker compose exec -T keycloak bash -ec 'exec 3<>/dev/tcp/127.0.0.1/9000; printf "GET /health/ready HTTP/1.1\\r\\nHost: localhost\\r\\nConnection: close\\r\\n\\r\\n" >&3; grep -q "200 OK" <&3'
curl --fail --silent --show-error "https://${KEYCLOAK_HOSTNAME}/realms/master" >/dev/null
```

Require an encrypted, checksummed PostgreSQL logical dump and a temporary restore verification before upgrades. State that the hostname is deployment-specific, PostgreSQL and port 9000 are never exposed, bootstrap secrets stay out of the repository, and this PR does not enable SSF user authentication.

- [ ] **Step 4: Run focused tests and the relevant quality checks**

Run:

```bash
pytest tests/test_keycloak_compose_configuration.py tests/test_clickhouse_compose_configuration.py tests/test_frontend_container_build.py -q
git diff origin/main...HEAD --check
```

Expected: all selected tests pass and the diff check is silent.

- [ ] **Step 5: Commit the operational documentation**

Run:

```bash
git add docs/README.md docs/deployment/BACKUP_STRATEGY.md docs/deployment/SECURITY.md docs/operations/runbooks/keycloak-operations.md tests/test_keycloak_compose_configuration.py
git commit -m "docs: add Keycloak operations runbook"
```

Expected: one focused commit makes the deployment supportable without introducing authentication configuration.

### Task 5: Create and validate the pull request

**Files:**
- Modify: no project files
- Test: full relevant test suite and PR diff inspection

**Interfaces:**
- Consumes: the rebased, passing feature branch.
- Produces: a GitHub pull request targeting `main`, linked to SSF issue #266 as explicitly out-of-scope follow-up work.

- [ ] **Step 1: Run final verification**

Run:

```bash
pytest tests/test_keycloak_compose_configuration.py tests/test_clickhouse_compose_configuration.py tests/test_frontend_container_build.py -q
docker compose --env-file <(printf '%s\\n' 'CLICKHOUSE_DB=test' 'CLICKHOUSE_USER=test' 'CLICKHOUSE_PASSWORD=test' 'KEYCLOAK_HOSTNAME=auth.test.example' 'KEYCLOAK_DB_NAME=keycloak' 'KEYCLOAK_DB_USER=keycloak' 'KEYCLOAK_DB_PASSWORD=test' 'KEYCLOAK_BOOTSTRAP_ADMIN_USERNAME=admin' 'KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD=test') config --quiet
git diff origin/main...HEAD --check
git status --short
```

Expected: all commands succeed and `git status --short` is empty.

- [ ] **Step 2: Inspect the exact PR diff**

Run:

```bash
git log --oneline origin/main..HEAD
git diff --stat origin/main...HEAD
git diff --check origin/main...HEAD
```

Expected: only Keycloak infrastructure, its contract tests, and its operations documentation are included.

- [ ] **Step 3: Push the branch and create the pull request**

Run:

```bash
git push --set-upstream origin feat/keycloak-infrastructure
gh pr create --base main --head feat/keycloak-infrastructure --title "feat: add Keycloak infrastructure foundation" --body "## Summary
- deploy a pinned Keycloak instance behind Traefik with private PostgreSQL
- configure the public hostname through \`KEYCLOAK_HOSTNAME\`
- add Compose security-contract tests and an operations runbook

## Out of scope
This PR does not configure realms, clients, roles, claims, Studio provisioning, or SSF login. Those runtime-configuration and authorization changes follow [#266](https://github.com/smart-village-solutions/smart-speech-flow/issues/266).

## Verification
- \`pytest tests/test_keycloak_compose_configuration.py tests/test_clickhouse_compose_configuration.py tests/test_frontend_container_build.py -q\`
- \`docker compose ... config --quiet\`"
```

Expected: the PR targets `main`, describes the infrastructure-only scope, and records the executed verification.

## Self-Review

- Spec coverage: Task 2 delivers the pinned image, private database, health checks, persistent volume, required hostname, credentials, and Traefik-only route. Task 3 preserves existing isolated Compose callers. Task 4 delivers the runbook, backup, security, and navigation documentation. Task 5 verifies and opens the scope-limited PR.
- Exclusions: The global constraints and Tasks 2, 4, and 5 explicitly exclude realm/client/role/claim provisioning, SSF login, Studio integration, and Node migration.
- Placeholder scan: no deferred implementation markers are used; every task names exact files, commands, configuration names, and expected outcomes.
- Interface consistency: `KEYCLOAK_HOSTNAME`, `keycloak`, `keycloak-postgres`, and `keycloak-postgres-data` use the same names in every task.
