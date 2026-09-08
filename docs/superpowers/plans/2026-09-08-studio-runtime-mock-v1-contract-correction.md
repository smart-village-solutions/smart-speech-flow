# Studio Runtime Mock V1 Contract Correction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Studio Runtime Configuration mock contract-faithful, protected, and directly swappable with the future Studio endpoint.

**Architecture:** The mock keeps the real V1 path but requires a fixed mock service token, the canonical Studio tenant header, and a correlation ID. Compose returns to loopback-only exposure. Consumers address it through a configurable base URL: local SSF containers use `http://studio-mock:8000`; replacing that single base URL with the Studio origin preserves the endpoint path and request/response contract.

**Tech Stack:** FastAPI, Pydantic, Docker Compose, pytest, GitHub Issues.

**Spec:** `docs/superpowers/specs/2026-09-08-studio-runtime-configuration-mock-v1-contract-correction-design.md`

## Global Constraints

- The mock MUST use `Authorization`, `X-Studio-Tenant-Id`, and `X-Correlation-Id`; it MUST reject legacy headers and every query selector.
- The mock MUST bind only to `127.0.0.1:8010` when its profile is explicitly enabled.
- The mock MUST return only fixed, non-sensitive data and no Traefik route.
- The caller-facing base URL is configurable; never hard-code a mock host in SSF client code.

---

### Task 1: Implement the V1 request and response surface

**Files:**
- Modify: `services/studio_mock/app.py`
- Modify: `tests/test_studio_runtime_configuration_mock.py`
- Modify: `openspec/changes/add-studio-runtime-configuration-mock/`

**Interfaces:**
- Consumes: `Authorization: Bearer studio-mock-authorized-token`, `X-Studio-Tenant-Id`, and `X-Correlation-Id`.
- Produces: a V1 configuration containing canonical SHA-256 `configurationRevision` and `authorizationRevision`.

- [x] **Step 1: Write failing V1 request-contract tests**

```python
def test_returns_v1_configuration_for_authorized_studio_instance() -> None:
    response = CLIENT.get(
        PATH,
        headers={
            "Authorization": "Bearer studio-mock-authorized-token",
            "X-Studio-Tenant-Id": "tenant-kassel",
            "X-Correlation-Id": "test-correlation-id",
        },
    )

    assert response.status_code == 200
    assert response.json()["localization"]["defaultLocale"] == "de-DE"
    assert "authorizationRevision" in response.json()
```

Add separate tests for missing/unknown token (`401`), known unauthorized token (`403`), missing Studio instance or correlation header (`400`), unknown instance (`404`), authorization projection pending (`409`), unavailable dependency (`503`), and rejected `tenantId` query selection.

- [x] **Step 2: Run the new tests to verify they fail**

Run: `pytest tests/test_studio_runtime_configuration_mock.py -q`

Expected: FAIL because the endpoint still accepts unauthenticated query-selected tenants and emits legacy localization fields.

- [x] **Step 3: Implement the minimum contract correction**

Implement the two fixed token states, require the three V1 headers, remove `tenantId`, add `400`, `401`, and `403` error documentation, rename the locale fields, and calculate both revisions from canonical payloads that exclude their respective revision fields.

- [x] **Step 4: Run focused verification**

Run: `pytest tests/test_studio_runtime_configuration_mock.py tests/test_studio_runtime_configuration_mock_compose.py -q && openspec validate add-studio-runtime-configuration-mock --strict`

Expected: PASS with V1 request, response, revision, error, and Compose tests green.

- [x] **Step 5: Commit**

```bash
git add services/studio_mock/app.py tests/test_studio_runtime_configuration_mock.py openspec/changes/add-studio-runtime-configuration-mock
git commit -m "fix(dev): align Studio mock with V1 contract"
```

### Task 2: Restore protected local operation and give implementers a swappable endpoint

**Files:**
- Modify: `docker-compose.yml`
- Modify: `docs/operations/keycloak-admin-access.md`
- Modify: `tests/test_studio_runtime_configuration_mock_compose.py`
- Modify: GitHub issue `#287`

**Interfaces:**
- Consumes: opt-in `studio-mock` Compose profile.
- Produces: loopback URL `http://127.0.0.1:8010` for host checks and Docker-network base URL `http://studio-mock:8000` for SSF implementation.

- [x] **Step 1: Write failing Compose and runbook tests**

```python
assert service["ports"] == ["127.0.0.1:8010:8000"]
assert "http://studio-mock:8000" in runbook
assert "studio-mock-authorized-token" in runbook
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_studio_runtime_configuration_mock_compose.py -q`

Expected: FAIL because the current mock binds to all host interfaces and the runbook documents an unauthenticated browser URL.

- [x] **Step 3: Apply protected-operation configuration and documentation**

Restore `127.0.0.1:8010:8000`. Document the required headers, both fixed test tokens, and the two base URLs. State that SSF must obtain the base URL from configuration (for example, `STUDIO_RUNTIME_CONFIGURATION_BASE_URL`) and retain `/internal/plugins/ssf/v1/runtime-configuration`, so replacing the mock requires only the base URL change.

- [x] **Step 4: Update implementation issue #287**

Post an English comment containing:

```text
Mock base URL for SSF containers: http://studio-mock:8000
Path: /internal/plugins/ssf/v1/runtime-configuration
Required headers: Authorization, X-Studio-Tenant-Id, X-Correlation-Id
Authorized test token: Bearer studio-mock-authorized-token
```

State that the client must make its base URL configurable and that production switches only that setting to Studio.

- [x] **Step 5: Rebuild, restart, and smoke test**

Run: `docker compose --profile studio-mock up -d --build --force-recreate studio-mock`

Verify an authorized `curl` to `127.0.0.1:8010` returns `tenant-kassel`, and verify Docker reports the loopback port mapping.

- [x] **Step 6: Commit**

```bash
git add docker-compose.yml docs/operations/keycloak-admin-access.md tests/test_studio_runtime_configuration_mock_compose.py
git commit -m "fix(dev): protect Studio mock endpoint"
```
