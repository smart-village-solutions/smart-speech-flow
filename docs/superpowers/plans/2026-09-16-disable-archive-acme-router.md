# Disable Archive ACME Router Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire the unresolvable archive frontend from production and block invalid ACME router hostnames before deployment changes containers.

**Architecture:** The production Compose overlay stops defining the archive service, while development Compose remains unchanged. The guarded deployment shell script reads rendered Compose YAML, identifies routers that use the `le` ACME resolver, extracts each `Host(`…`)` value, and rejects local-only or resolver-unreachable hosts before calling `production_compose up -d`.

**Tech Stack:** Docker Compose YAML, Bash, Python `pytest`, PyYAML.

**Spec:** `docs/superpowers/specs/2026-09-16-disable-archive-acme-router-design.md`

## Global Constraints

- Production keeps the Docker/File provider boundaries and ACME storage unchanged.
- `frontend-archive` is removed only from `deploy/production/docker-compose.production.yml`.
- ACME validation is pre-deployment and prevents `production_compose up -d` on failure.
- No DNS, Studio repository, or tenant-lifecycle mutation belongs in this change.

---

### Task 1: Retire the production archive route

**Files:**
- Modify: `deploy/production/docker-compose.production.yml: frontend-archive service`
- Modify: `tests/test_traefik_dynamic_configuration.py`

**Interfaces:**
- Consumes: production and development Compose definitions.
- Produces: a production overlay without the archive service or archive hostname.

- [ ] **Step 1: Write the failing Compose contract test**

```python
def test_production_retires_the_archive_frontend_but_development_keeps_it() -> None:
    production = yaml.safe_load(PRODUCTION_COMPOSE_PATH.read_text(encoding="utf-8"))
    development = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))

    assert "frontend-archive" not in production["services"]
    assert "frontend-archive" in development["services"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_traefik_dynamic_configuration.py::test_production_retires_the_archive_frontend_but_development_keeps_it -q`

Expected: FAIL because `frontend-archive` is present in production.

- [ ] **Step 3: Remove only the production archive mapping**

Delete the entire `frontend-archive` service block from `deploy/production/docker-compose.production.yml`. Leave `docker-compose.yml` unchanged.

- [ ] **Step 4: Run the focused Compose contracts**

Run: `.venv/bin/pytest tests/test_traefik_dynamic_configuration.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add deploy/production/docker-compose.production.yml tests/test_traefik_dynamic_configuration.py
git commit -m "fix(ops): retire archive production router"
```

### Task 2: Guard rendered ACME router hosts

**Files:**
- Modify: `scripts/deploy-production.sh`
- Modify: `tests/operations/test_production_scripts.py`

**Interfaces:**
- Consumes: `production_compose config` output and host `getent ahosts` resolution.
- Produces: `validate_production_config` that returns non-zero before `production_compose up -d` for invalid ACME hosts.

- [ ] **Step 1: Write failing behavioral tests with fake `docker` and `getent` binaries**

Provide a fake `docker`: `compose … config` prints `FAKE_RENDERED_COMPOSE`; `up -d` appends `up` to `FAKE_DOCKER_LOG`. A fake `getent` exits from `FAKE_GETENT_STATUS`.

```python
def test_deploy_check_rejects_a_local_acme_router_before_compose_up(tmp_path) -> None:
    rendered = """services:
  keycloak:
    labels:
      traefik.http.routers.keycloak.rule: Host(`auth.localhost`)
      traefik.http.routers.keycloak.tls.certresolver: le
"""
    result = run_script(
        "scripts/deploy-production.sh", "--apply",
        environment=fake_compose_environment(tmp_path, rendered, getent_status=0),
    )

    assert result.returncode == 1
    assert "auth.localhost" in result.stderr
    assert "up" not in (tmp_path / "docker.log").read_text()
```

Add equivalent tests for an unresolvable public-looking host (`getent_status=2`) and a resolving public host (`auth.dialog.kassel.de`, `getent_status=0`) that permits `up`.

- [ ] **Step 2: Run new tests and verify they fail**

Run: `.venv/bin/pytest tests/operations/test_production_scripts.py -k 'acme_router' -q`

Expected: FAIL because the current script neither examines router labels nor calls `getent`.

- [ ] **Step 3: Implement minimal shell validation**

Add `acme_router_hosts()` and `validate_acme_router_hosts()`; call the latter from `validate_production_config()` after the Keycloak checks. Parse the rendered labels with `awk`, pair `traefik.http.routers.<name>.tls.certresolver: le` with that router's rule, extract every `Host(`hostname`)`, and de-duplicate with `sort -u`.

```bash
[[ "$hostname" != "localhost" && "$hostname" != *.localhost ]] || {
  log_error "ACME router hostname is local-only: $hostname"; return 1;
}
getent ahosts "$hostname" >/dev/null || {
  log_error "ACME router hostname cannot be resolved: $hostname"; return 1;
}
```

- [ ] **Step 4: Run the production-script suite**

Run: `.venv/bin/pytest tests/operations/test_production_scripts.py -q`

Expected: PASS, including rejection before `up -d` and acceptance of a resolving host.

- [ ] **Step 5: Commit**

```bash
git add scripts/deploy-production.sh tests/operations/test_production_scripts.py
git commit -m "fix(ops): validate production ACME router hosts"
```

### Task 3: Validate the completed change

**Files:**
- Modify: `openspec/changes/disable-archive-acme-router/tasks.md`

**Interfaces:**
- Consumes: implementation and tests from Tasks 1–2.
- Produces: a verified OpenSpec change with an accurate completed checklist.

- [ ] **Step 1: Run verification**

Run: `.venv/bin/pytest tests/test_traefik_dynamic_configuration.py tests/operations/test_production_scripts.py -q && openspec validate disable-archive-acme-router --strict && git diff --check`

Expected: all tests pass, OpenSpec reports valid, and whitespace validation emits no errors.

- [ ] **Step 2: Mark the OpenSpec checklist complete after successful verification**

Replace the markers for each completed item in `openspec/changes/disable-archive-acme-router/tasks.md` with `- [x]`.

- [ ] **Step 3: Commit**

```bash
git add openspec/changes/disable-archive-acme-router/tasks.md
git commit -m "docs: record archive ACME router verification"
```
