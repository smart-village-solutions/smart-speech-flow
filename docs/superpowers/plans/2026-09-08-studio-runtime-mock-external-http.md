# Studio Runtime Mock External HTTP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the opt-in Studio Runtime Configuration mock readable without authentication at `http://<host-ip>:8010`.

**Architecture:** The Compose service remains profile-gated and is not placed behind Traefik. Its port mapping changes from loopback-only to all host interfaces, and the FastAPI endpoint no longer checks an `Authorization` header. Documentation gives the exact HTTP-by-IP invocation and states that the service deliberately exposes only fixed, non-sensitive test data.

**Tech Stack:** Docker Compose, FastAPI, pytest.

**Spec:** `openspec/changes/add-studio-runtime-configuration-mock/`

## Global Constraints

- The `studio-mock` service MUST remain disabled unless the `studio-mock` profile is explicitly selected.
- The HTTP endpoint MUST NOT require authentication.
- The mock MUST NOT receive a Traefik route or production service dependency.

---

### Task 1: Publish and document the opt-in HTTP port

**Files:**
- Modify: `docker-compose.yml:184-198`
- Modify: `services/studio_mock/app.py:130-165`
- Modify: `docs/operations/keycloak-admin-access.md:21-40`
- Modify: `tests/test_studio_runtime_configuration_mock.py`
- Test: `tests/test_studio_runtime_configuration_mock_compose.py`

**Interfaces:**
- Consumes: Docker Compose `studio-mock` profile and existing port 8010.
- Produces: unauthenticated `http://<host-ip>:8010/internal/plugins/ssf/v1/runtime-configuration`.

- [x] **Step 1: Write the failing endpoint and Compose regression tests**

```python
def test_returns_configuration_without_authorization() -> None:
    response = CLIENT.get(
        PATH,
        headers={"X-Tenant-Id": "tenant-kassel", "X-Correlation-Id": "test-correlation-id"},
    )

    assert response.status_code == 200


def test_studio_mock_publishes_http_port_on_all_interfaces() -> None:
    compose = yaml.safe_load(Path("docker-compose.yml").read_text())

    assert compose["services"]["studio-mock"]["ports"] == ["8010:8000"]
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_studio_runtime_configuration_mock.py::test_returns_configuration_without_authorization tests/test_studio_runtime_configuration_mock_compose.py::test_studio_mock_publishes_http_port_on_all_interfaces -v`

Expected: FAIL because the endpoint currently returns `401` and the mapping is `127.0.0.1:8010:8000`.

- [x] **Step 3: Change the port mapping and runbook**

```yaml
ports:
  - "8010:8000"
```

Remove the endpoint's `Authorization` parameter and its `401`/`403` paths, and change the port mapping to `8010:8000`. Document `http://<host-ip>:8010/internal/plugins/ssf/v1/runtime-configuration` as unauthenticated and limited to fixed, non-sensitive test data.

- [x] **Step 4: Run focused verification**

Run: `pytest tests/test_studio_runtime_configuration_mock.py tests/test_studio_runtime_configuration_mock_compose.py -q && openspec validate add-studio-runtime-configuration-mock --strict`

Expected: PASS with all mock and Compose tests passing and a valid OpenSpec change.

- [x] **Step 5: Commit**

```bash
git add docker-compose.yml docs/operations/keycloak-admin-access.md tests/test_studio_runtime_configuration_mock_compose.py openspec/changes/add-studio-runtime-configuration-mock docs/superpowers/plans/2026-09-08-studio-runtime-mock-external-http.md
git commit -m "feat(dev): expose Studio mock over HTTP"
```
