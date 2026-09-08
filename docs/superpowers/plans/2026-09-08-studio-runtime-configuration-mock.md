# Studio Runtime Configuration Mock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a local, contract-faithful Studio Runtime Configuration V1 mock API without changing production behavior.

**Architecture:** A small standalone FastAPI service returns deterministic V1 configuration fixtures and documented error envelopes. A Compose `studio-mock` profile packages it only for local integration tests; no SSF production service is rewired to it.

**Tech Stack:** Python 3.12, FastAPI, pytest, Docker Compose.

**Spec:** `openspec/changes/add-studio-runtime-configuration-mock/`

## Global Constraints

- Implement only the published Studio Runtime Configuration Contract V1 endpoint.
- Use no real credentials or production URLs.
- Keep the mock disabled unless the local `studio-mock` Compose profile is selected.

---

### Task 1: Contract fixtures and HTTP endpoint

**Files:**
- Create: `services/studio_mock/app.py`
- Create: `services/studio_mock/__init__.py`
- Test: `tests/test_studio_runtime_configuration_mock.py`

**Interfaces:**
- Produces: `app`, a FastAPI application serving `GET /internal/plugins/ssf/v1/runtime-configuration`.
- Consumes: `Authorization`, `X-Tenant-Id`, and `X-Correlation-Id` request headers.

- [ ] **Step 1: Write failing tests** for accepted test bearer token, both tenant policies, unknown tenant, invalid token, and selected `409`/`503` envelopes.
- [ ] **Step 2: Run** `pytest tests/test_studio_runtime_configuration_mock.py -q` and confirm the endpoint is absent.
- [ ] **Step 3: Implement** the smallest deterministic fixtures, header validation, endpoint, and error envelope helper needed for the tests.
- [ ] **Step 4: Run** `pytest tests/test_studio_runtime_configuration_mock.py -q` and confirm it passes.
- [ ] **Step 5: Commit** the endpoint and tests.

### Task 2: Opt-in container delivery

**Files:**
- Create: `services/studio_mock/Dockerfile`
- Modify: `docker-compose.yml`
- Test: `tests/test_studio_runtime_configuration_mock_compose.py`

**Interfaces:**
- Produces: `studio-mock` Compose service enabled only by profile `studio-mock`.

- [ ] **Step 1: Write a failing Compose contract test** proving the service declares the profile and default Compose does not include it.
- [ ] **Step 2: Run** `pytest tests/test_studio_runtime_configuration_mock_compose.py -q` and confirm it fails.
- [ ] **Step 3: Implement** a minimal Python image and opt-in Compose service with no public production route.
- [ ] **Step 4: Run** the Compose contract test and `docker compose config` with and without `--profile studio-mock`.
- [ ] **Step 5: Commit** the container delivery changes.

### Task 3: Operator documentation and verification

**Files:**
- Modify: `docs/operations/keycloak-admin-access.md`
- Test: `tests/test_studio_runtime_configuration_mock.py`

**Interfaces:**
- Documents: local start command, test token, tenant identifiers, error scenario selection, and production exclusion.

- [ ] **Step 1: Add a failing documentation assertion** requiring the local profile and production exclusion text.
- [ ] **Step 2: Run** the focused tests and confirm the assertion fails.
- [ ] **Step 3: Document** the mock operation and its non-production boundary.
- [ ] **Step 4: Run** all mock-focused tests and `docker compose --profile studio-mock config`.
- [ ] **Step 5: Commit** the documentation and verification changes.
