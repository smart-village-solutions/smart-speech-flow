# Studio Runtime Flow MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compose the existing Studio tenant, token, and V1-client foundations into a fail-closed runtime-configuration dependency for authenticated SSF work.

**Architecture:** Add the signed authorization revision to the existing immutable tenant context. A new runtime-flow service calls the existing client, compares its response revision, and returns a validated value object. A FastAPI dependency resolves a safe correlation ID and exposes this object without a new endpoint.

**Tech Stack:** Python 3.12, FastAPI dependencies, Pydantic, aiohttp, pytest, pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-09-09-studio-runtime-flow-design.md`

## Global Constraints

- Derive runtime authorization only from validated `studio_tenant_id` and `ssf_authorization_revision` claims.
- Do not modify the existing token-provider cache, Runtime Configuration V1 client, or client schemas.
- Never accept a browser tenant selector or return fallback configuration.
- The existing V1 client alone emits `X-Studio-Tenant-Id` and `X-Correlation-Id`.

---

### Task 1: Extend the trusted tenant context

**Files:**
- Modify: `services/api_gateway/tenant_context.py:31-53`
- Test: `tests/test_tenant_context.py`

**Interfaces:** Produces `StudioTenantContext(tenant_id: str, authorization_revision: str)` from validated `require_ssf_user` claims.

- [ ] **Step 1: Write the failing tests**

```python
def test_context_requires_a_signed_authorization_revision() -> None:
    context = studio_tenant_context_from_claims(
        {"studio_tenant_id": "tenant-kassel", "ssf_authorization_revision": REVISION}
    )
    assert context.authorization_revision == REVISION

@pytest.mark.parametrize("revision", [None, "", "sha256:UPPERCASE"])
def test_context_rejects_invalid_authorization_revisions(revision: object) -> None:
    with pytest.raises(HTTPException):
        studio_tenant_context_from_claims(
            {"studio_tenant_id": "tenant-kassel", "ssf_authorization_revision": revision}
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tenant_context.py -q`

Expected: FAIL because `StudioTenantContext` has no `authorization_revision`.

- [ ] **Step 3: Write minimal implementation**

```python
@dataclass(frozen=True)
class StudioTenantContext:
    tenant_id: str
    authorization_revision: str

authorization_revision = claims.get("ssf_authorization_revision")
if not isinstance(authorization_revision, str) or not REVISION_PATTERN.fullmatch(authorization_revision):
    raise _invalid_tenant_claim()
```

Use the V1 SHA-256 format from `studio_runtime_client.REVISION_PATTERN` or a shared dependency-safe pattern. Reject legacy/conflicting claims.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tenant_context.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Commit `services/api_gateway/tenant_context.py` and `tests/test_tenant_context.py` with `feat: require Studio authorization revision`.

### Task 2: Add the fail-closed runtime-flow service

**Files:**
- Create: `services/api_gateway/studio_runtime_flow.py`
- Test: `tests/test_studio_runtime_flow.py`

**Interfaces:** Consumes `StudioTenantContext`, `StudioRuntimeClient.fetch(tenant_id, correlation_id)`, and `RuntimeConfiguration`. Produces `ValidatedRuntimeConfiguration(context, configuration, correlation_id)` and `StudioRuntimeFlowError(code, retryable)`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_flow_returns_configuration_only_for_matching_revision() -> None:
    flow = StudioRuntimeFlow(client=StubClient(configuration_for("tenant-kassel", REVISION)))
    result = await flow.resolve(context("tenant-kassel", REVISION), "correlation-1")
    assert result.configuration.tenant.id == "tenant-kassel"

@pytest.mark.asyncio
async def test_flow_rejects_mismatching_authorization_revision() -> None:
    flow = StudioRuntimeFlow(client=StubClient(configuration_for("tenant-kassel", OTHER_REVISION)))
    with pytest.raises(StudioRuntimeFlowError, match="studio_runtime_authorization_mismatch"):
        await flow.resolve(context("tenant-kassel", REVISION), "correlation-1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_studio_runtime_flow.py -q`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
@dataclass(frozen=True)
class ValidatedRuntimeConfiguration:
    context: StudioTenantContext
    configuration: RuntimeConfiguration
    correlation_id: str

async def resolve(self, context: StudioTenantContext, correlation_id: str) -> ValidatedRuntimeConfiguration:
    configuration = await self._client.fetch(context.tenant_id, correlation_id)
    if not hmac.compare_digest(configuration.authorization_revision, context.authorization_revision):
        raise StudioRuntimeFlowError("studio_runtime_authorization_mismatch", retryable=False)
    return ValidatedRuntimeConfiguration(context, configuration, correlation_id)
```

Translate existing token/client errors into safe flow errors, without exception bodies or configuration fallback.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_studio_runtime_flow.py -q`

Expected: PASS, including upstream failure and tenant-mismatch propagation.

- [ ] **Step 5: Commit**

Commit `services/api_gateway/studio_runtime_flow.py` and `tests/test_studio_runtime_flow.py` with `feat: add tenant-bound Studio runtime flow`.

### Task 3: Expose the authenticated dependency and correlation behavior

**Files:**
- Modify: `services/api_gateway/studio_runtime_flow.py`
- Test: `tests/test_studio_runtime_flow.py`

**Interfaces:** Consumes `Request`, `require_studio_tenant_context`, and `StudioRuntimeFlow`. Produces a `require_validated_runtime_configuration` FastAPI dependency.

- [ ] **Step 1: Write the failing tests**

```python
def test_dependency_forwards_valid_correlation_id(client: TestClient) -> None:
    response = client.get("/runtime-operation", headers={"X-Correlation-Id": "request-123"})
    assert response.json()["correlation_id"] == "request-123"

def test_dependency_generates_correlation_id_when_absent(client: TestClient) -> None:
    response = client.get("/runtime-operation")
    assert UUID(response.json()["correlation_id"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_studio_runtime_flow.py -q`

Expected: FAIL because no dependency resolves the flow or correlation ID.

- [ ] **Step 3: Write minimal implementation**

```python
async def require_validated_runtime_configuration(
    request: Request,
    context: Annotated[StudioTenantContext, Depends(require_studio_tenant_context)],
) -> ValidatedRuntimeConfiguration:
    correlation_id = request.headers.get("X-Correlation-Id") or str(uuid4())
    return await runtime_flow_from_environment().resolve(context, correlation_id)
```

Validate supplied IDs before calling Studio and map unsafe input or runtime failures to safe `HTTPException` responses. Do not add a public route.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_studio_runtime_flow.py tests/test_tenant_context.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Commit the flow module and tests with `feat: expose validated Studio runtime dependency`.

### Task 4: Validate the change

**Files:**
- Modify: `openspec/changes/integrate-studio-runtime-flow/tasks.md`

- [ ] **Step 1: Mark only completed task items**

Update the OpenSpec checklist after its associated code and tests have passed.

- [ ] **Step 2: Run focused verification**

Run: `pytest tests/test_tenant_context.py tests/test_studio_runtime_flow.py tests/test_studio_runtime_client.py tests/test_studio_runtime_token.py -q`

Expected: PASS.

- [ ] **Step 3: Validate OpenSpec**

Run: `openspec validate integrate-studio-runtime-flow --strict`

Expected: PASS.

- [ ] **Step 4: Commit the completed checklist**

Commit the completed OpenSpec checklist with `docs: complete Studio runtime flow change tasks`.
