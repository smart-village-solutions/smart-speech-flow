# Tenant-Isolated Conversation Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every conversation resource tenant-isolated, preserve the tenant-free customer join URL, and provide a destructive production cutover for the currently unused server.

**Architecture:** A single conversation core addresses resources with `TenantSessionKey(tenant_id, session_id)`. Admin calls derive the tenant from `StudioTenantContext`; customer calls resolve the public session capability through a server-owned join index. Redis, audio, realtime, polling, monitoring, and runtime-configuration state all retain that key through their complete lifecycle.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, redis-py, pytest, React 19, TypeScript 6, Axios, Keycloak JS, Vitest, Docker Compose, Bash

**Spec:** `docs/superpowers/specs/2026-09-11-tenant-isolation-design.md`

## Global Constraints

- This is a destructive hard cut: do not read, migrate, or provide compatibility for legacy conversation state.
- Admin tenant identity comes only from `StudioTenantContext`; never accept a tenant selector from a path, query, header, cookie, or body.
- Keep the public URL `/join/:sessionId`; customer APIs resolve its tenant from the server-owned join index.
- Return the same neutral HTTP 404 for an unknown resource and a cross-tenant resource.
- Never put a Keycloak JWT in a WebSocket URL; admin realtime uses a single-use opaque ticket with a maximum lifetime of 60 seconds.
- Heartbeats indicate transport presence, not conversation activity.
- A connected admin keeps a session alive; after the last admin disconnect there is a 30-minute grace period with a warning five minutes before termination; absolute lifetime is eight hours.
- Use Redis schema prefix `ssf:v2` and audio root `/data/audio/v2`; runtime code must not read legacy session keys or legacy audio paths.
- Set `SSF_ENABLE_LEGACY_ADMIN_ACCESS=false` for the tenant-isolated deployment.
- Logs may contain `tenant_ref = sha256(tenant_id)[:12]`, but no raw tenant ID, realm, bearer token, join capability, realtime ticket, or audio path.
- Prometheus labels remain aggregate or fixed-cardinality; never add tenant IDs, tenant references, or session IDs as metric labels.
- All new or modified project documentation is written in English.

---

### Task 1: Introduce tenant session identity and immutable configuration snapshots

**Files:**
- Create: `services/api_gateway/tenant_session.py`
- Modify: `services/api_gateway/session_manager.py`
- Create: `tests/test_tenant_session.py`
- Modify: `tests/test_studio_runtime_flow.py`

**Interfaces:**
- Produces: `TenantSessionKey(tenant_id: str, session_id: str)` with `tenant_ref` and `redis_tenant_component` properties.
- Produces: `RuntimeConfigurationSnapshot.from_configuration(configuration)` and `.to_configuration()`.
- Produces: `ClientType`, `SessionStatus`, `SessionMessage`, and `Session` in `tenant_session.py`, eliminating a circular import between the manager and store.
- Produces: `Session.key: TenantSessionKey`; `Session.tenant_id` and `Session.runtime_configuration` are mandatory constructor fields. `session_manager.py` re-exports the four moved model names while existing call sites are migrated.

- [ ] **Step 1: Write failing value-object and serialization tests**

```python
def test_tenant_session_key_uses_unpadded_urlsafe_redis_component():
    key = TenantSessionKey("stadt:kassel/ä", "ABC12345")
    assert key.redis_tenant_component == "c3RhZHQ6a2Fzc2VsL8Ok"
    assert key.tenant_ref == sha256(b"stadt:kassel/\xc3\xa4").hexdigest()[:12]


def test_session_round_trip_requires_tenant_and_frozen_runtime_configuration(runtime_configuration):
    snapshot = RuntimeConfigurationSnapshot.from_configuration(runtime_configuration)
    session = Session(
        id="ABC12345",
        tenant_id="tenant-a",
        runtime_configuration=snapshot,
    )
    restored = Session.from_dict(session.to_dict(include_messages=True))
    assert restored.key == TenantSessionKey("tenant-a", "ABC12345")
    assert restored.runtime_configuration == snapshot
    assert restored.runtime_configuration.to_configuration() == runtime_configuration
```

- [ ] **Step 2: Run the focused tests and verify the new types are missing**

Run: `pytest -q tests/test_tenant_session.py tests/test_studio_runtime_flow.py`

Expected: FAIL during collection because `tenant_session` and the mandatory `Session` fields do not exist.

- [ ] **Step 3: Implement validated immutable value objects**

```python
@dataclass(frozen=True, slots=True)
class TenantSessionKey:
    tenant_id: str
    session_id: str

    def __post_init__(self) -> None:
        if not self.tenant_id or len(self.tenant_id) > 128:
            raise ValueError("tenant_id must contain 1..128 characters")
        if not SESSION_ID_PATTERN.fullmatch(self.session_id):
            raise ValueError("invalid session_id")

    @property
    def redis_tenant_component(self) -> str:
        encoded = base64.urlsafe_b64encode(self.tenant_id.encode("utf-8"))
        return encoded.decode("ascii").rstrip("=")

    @property
    def tenant_ref(self) -> str:
        return sha256(self.tenant_id.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True, slots=True)
class RuntimeConfigurationSnapshot:
    configuration_revision: str
    authorization_revision: str
    canonical_json: str

    @classmethod
    def from_configuration(cls, value: RuntimeConfiguration) -> "RuntimeConfigurationSnapshot":
        payload = value.model_dump(mode="json", by_alias=True)
        return cls(
            configuration_revision=value.configuration_revision,
            authorization_revision=value.authorization_revision,
            canonical_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
        )

    def to_configuration(self) -> RuntimeConfiguration:
        return RuntimeConfiguration.model_validate_json(self.canonical_json)
```

Move `ClientType`, `SessionStatus`, `SessionMessage`, and `Session` from
`session_manager.py` into this module. Update `Session.to_dict()` and
`Session.from_dict()` to require and round-trip `tenant_id` plus the complete
snapshot. Do not supply defaults that could load legacy payloads.

- [ ] **Step 4: Run focused tests and static checks**

Run: `pytest -q tests/test_tenant_session.py tests/test_studio_runtime_flow.py && mypy services/api_gateway/tenant_session.py services/api_gateway/session_manager.py`

Expected: PASS.

- [ ] **Step 5: Commit the tenant identity model**

```bash
git add services/api_gateway/tenant_session.py services/api_gateway/session_manager.py tests/test_tenant_session.py tests/test_studio_runtime_flow.py
git commit -m "feat: add tenant session identity"
```

### Task 2: Replace legacy persistence with an atomic Redis v2 store

**Files:**
- Create: `services/api_gateway/session_store.py`
- Modify: `services/api_gateway/session_manager.py`
- Create: `tests/test_tenant_session_store.py`
- Modify: `tests/test_session_manager.py`

**Interfaces:**
- Consumes: `TenantSessionKey`, `Session.to_dict(include_messages=True)`, and `Session.from_dict()` from Task 1.
- Produces: `TenantSessionStore` protocol and `MemoryTenantSessionStore` / `RedisTenantSessionStore` implementations.
- Produces: `create(session: Session) -> bool`, `save(session: Session) -> None`, `load(key) -> Session | None`, `resolve_join(session_id) -> TenantSessionKey | None`, `list_for_tenant(tenant_id) -> list[Session]`, and `terminate(session) -> None`.

- [ ] **Step 1: Write failing key, atomicity, collision, and corruption tests**

```python
def test_v2_keys_include_encoded_tenant():
    key = TenantSessionKey("tenant-a", "ABC12345")
    assert session_key("ssf", key) == "ssf:v2:tenant:dGVuYW50LWE:session:ABC12345"
    assert tenant_sessions_key("ssf", "tenant-a") == "ssf:v2:tenant:dGVuYW50LWE:sessions"
    assert join_key("ssf", "ABC12345") == "ssf:v2:join:ABC12345"


def test_create_is_atomic_and_refuses_a_global_join_collision(redis_store, session_a, session_b):
    assert redis_store.create(session_a) is True
    session_b.id = session_a.id
    assert redis_store.create(session_b) is False
    assert redis_store.resolve_join(session_a.id) == session_a.key
    assert redis_store.list_for_tenant("tenant-b") == []


def test_mismatched_payload_and_join_index_fail_closed(
    redis_store, session_a, session_b_payload
):
    redis_store.create(session_a)
    redis_store.redis.set(session_key("ssf", session_a.key), session_b_payload)
    assert redis_store.load(session_a.key) is None
    assert redis_store.resolve_join(session_a.id) is None
```

The test double records `EVAL` keys and arguments so assertions prove the create and terminate mutations are a single Redis script invocation.

- [ ] **Step 2: Run the store tests and verify they fail before implementation**

Run: `pytest -q tests/test_tenant_session_store.py tests/test_session_manager.py`

Expected: FAIL because `session_store.py` does not exist.

- [ ] **Step 3: Implement the store protocol, exact v2 keys, and Lua mutations**

```python
class TenantSessionStore(Protocol):
    def create(self, session: Session) -> bool:
        raise NotImplementedError

    def save(self, session: Session) -> None:
        raise NotImplementedError

    def load(self, key: TenantSessionKey) -> Session | None:
        raise NotImplementedError

    def resolve_join(self, session_id: str) -> TenantSessionKey | None:
        raise NotImplementedError

    def list_for_tenant(self, tenant_id: str) -> list[Session]:
        raise NotImplementedError

    def terminate(self, session: Session) -> None:
        raise NotImplementedError


CREATE_SESSION_LUA = """
if redis.call('EXISTS', KEYS[3]) == 1 then return 0 end
redis.call('SET', KEYS[1], ARGV[1])
redis.call('SADD', KEYS[2], ARGV[2])
redis.call('SET', KEYS[3], ARGV[3])
redis.call('SADD', KEYS[4], ARGV[2])
return 1
"""

TERMINATE_SESSION_LUA = """
redis.call('SET', KEYS[1], ARGV[1])
redis.call('SREM', KEYS[2], ARGV[2])
if redis.call('GET', KEYS[3]) == ARGV[3] then redis.call('SET', KEYS[3], ARGV[4]) end
return 1
"""
```

Serialize the join value as canonical JSON containing `tenant_id`, `session_id`,
and `active`. Termination atomically changes `active` from true to false instead
of deleting the join tombstone; this prevents any historical session ID from
being reused while making customer resolution reject it. On every load,
validate payload tenant, key tenant, payload session, and join value with
`hmac.compare_digest`; on mismatch return `None` and emit only pseudonymous
references. Remove all reads of `ssf:session:*`, `ssf:sessions`, and
`ssf:session:active_admin` from `SessionManager`.

- [ ] **Step 4: Run the persistence and manager tests**

Run: `pytest -q tests/test_tenant_session_store.py tests/test_session_manager.py`

Expected: PASS, including collision and corrupt-index cases.

- [ ] **Step 5: Commit the v2 persistence boundary**

```bash
git add services/api_gateway/session_store.py services/api_gateway/session_manager.py tests/test_tenant_session_store.py tests/test_session_manager.py
git commit -m "feat: add tenant-scoped session persistence"
```

### Task 3: Make lifecycle, presence, and timeouts tenant-aware

**Files:**
- Modify: `services/api_gateway/session_manager.py`
- Modify: `services/api_gateway/app.py`
- Rewrite: `tests/test_session_manager.py`
- Rewrite: `tests/test_session_timeout.py`
- Modify: `.env.example`

**Interfaces:**
- Consumes: `TenantSessionStore` and `RuntimeConfigurationSnapshot` from Tasks 1–2.
- Produces: `create_admin_session(tenant_id, snapshot) -> Session`, `get_session(key)`, `resolve_customer_session(session_id)`, tenant-scoped list/current/history/terminate/message methods, and connection-count methods.
- Produces: `Session.next_timeout_at() -> datetime`, `Session.warning_due(now) -> bool`, and `Session.timeout_due(now) -> bool`.

- [ ] **Step 1: Replace global-session tests with a two-tenant lifecycle matrix**

```python
@pytest.mark.asyncio
async def test_single_active_session_limit_is_per_tenant(manager, snapshots):
    a1 = await manager.create_admin_session("tenant-a", snapshots.a)
    b1 = await manager.create_admin_session("tenant-b", snapshots.b)
    a2 = await manager.create_admin_session("tenant-a", snapshots.a)
    assert manager.get_session(a1.key).status is SessionStatus.TERMINATED
    assert manager.get_session(b1.key).status is SessionStatus.PENDING
    assert manager.get_session(a2.key).status is SessionStatus.PENDING


def test_connected_admin_survives_silence_but_absolute_limit_wins(session, clock):
    session.admin_connection_count = 1
    clock.advance(hours=7, minutes=55)
    assert session.warning_due(clock.now()) is True
    clock.advance(minutes=4)
    assert session.timeout_due(clock.now()) is False
    clock.advance(minutes=1)
    assert session.timeout_due(clock.now()) is True


def test_customer_alone_does_not_cancel_admin_reconnect_grace(session, clock):
    session.admin_connection_count = 0
    session.customer_connection_count = 1
    session.admin_disconnected_at = clock.now()
    clock.advance(minutes=25)
    assert session.warning_due(clock.now()) is True
    clock.advance(minutes=5)
    assert session.timeout_due(clock.now()) is True
```

Also cover: an orphaned PENDING session uses `created_at` as its grace anchor;
first admin connect clears that anchor; reconnect within 30 minutes cancels the
warning; heartbeat does not alter timeout state; termination closes only the
exact `TenantSessionKey`; and serialized status exposes `warning_at` and
`timeout_at` derived from the earliest reconnect or absolute deadline.

Session-ID allocation uses 32 attempts and checks the permanent global join
tombstone on every attempt. It never overwrites a historical session record or
reuses an identifier after termination.

- [ ] **Step 2: Run lifecycle tests and verify legacy global behavior fails**

Run: `pytest -q tests/test_session_manager.py tests/test_session_timeout.py`

Expected: FAIL because manager methods still accept only `session_id` and heartbeats still update `last_activity`.

- [ ] **Step 3: Implement tenant-scoped manager state and presence semantics**

```python
self.sessions: dict[TenantSessionKey, Session] = {}
self.join_index: dict[str, TenantSessionKey] = {}
self.active_admin_sessions: dict[str, set[str]] = defaultdict(set)

async def create_admin_session(
    self, tenant_id: str, runtime_configuration: RuntimeConfigurationSnapshot
) -> Session:
    if not self.allow_parallel_sessions:
        await self.terminate_all_active_sessions(tenant_id, "new_session_created")
    for _attempt in range(32):
        session = Session(
            id=self.session_id_factory(),
            tenant_id=tenant_id,
            runtime_configuration=runtime_configuration,
        )
        if self.store.create(session):
            self.sessions[session.key] = session
            self.join_index[session.id] = session.key
            self.active_admin_sessions[tenant_id].add(session.id)
            return session
    raise SessionIdCollisionError("could not allocate a globally unique session id")

def admin_connected(self, key: TenantSessionKey) -> None:
    session = self.require_session(key)
    session.admin_connection_count += 1
    session.admin_disconnected_at = None
    session.timeout_warning_sent = False
    self.store.save(session)

def admin_disconnected(self, key: TenantSessionKey) -> None:
    session = self.require_session(key)
    session.admin_connection_count = max(0, session.admin_connection_count - 1)
    if session.admin_connection_count == 0:
        session.admin_disconnected_at = self.clock()
    self.store.save(session)
```

Read validated positive values from `SSF_SESSION_RECONNECT_GRACE_MINUTES=30`, `SSF_SESSION_TIMEOUT_WARNING_MINUTES=5`, and `SSF_SESSION_MAX_HOURS=8`. The periodic checker iterates `(TenantSessionKey, Session)` pairs and preserves the key for warnings, realtime cleanup, persistence, and termination. `heartbeat_received` updates only connection heartbeat metadata.

- [ ] **Step 4: Run focused and lifecycle telemetry regression tests**

Run: `pytest -q tests/test_session_manager.py tests/test_session_timeout.py tests/test_session_lifecycle_emission.py`

Expected: PASS.

- [ ] **Step 5: Commit tenant-aware lifecycle behavior**

```bash
git add services/api_gateway/session_manager.py services/api_gateway/app.py tests/test_session_manager.py tests/test_session_timeout.py tests/test_session_lifecycle_emission.py .env.example
git commit -m "feat: isolate tenant session lifecycle"
```

### Task 4: Enforce tenant access at admin and customer HTTP boundaries

**Files:**
- Create: `services/api_gateway/session_access.py`
- Modify: `services/api_gateway/auth.py`
- Modify: `services/api_gateway/routes/admin.py`
- Modify: `services/api_gateway/routes/customer.py`
- Modify: `services/api_gateway/routes/session.py`
- Modify: `services/api_gateway/app.py`
- Modify: `tests/conftest.py`
- Create: `tests/test_tenant_session_access.py`
- Modify: `tests/test_auth.py`
- Modify: `services/api_gateway/tests/test_admin.py`
- Modify: `services/api_gateway/tests/test_customer.py`

**Interfaces:**
- Consumes: tenant-aware manager methods from Task 3 and `require_validated_runtime_configuration`.
- Produces: `require_admin_session_key(session_id, context) -> TenantSessionKey` and `require_customer_session_key(session_id, optional_context) -> TenantSessionKey`.
- Produces: `optional_ssf_user` which returns `None` only when Authorization is absent; malformed or invalid supplied credentials still fail authentication.

- [ ] **Step 1: Write failing positive and cross-tenant HTTP tests**

```python
def test_admin_create_binds_validated_runtime_configuration(client, tenant_a_auth, runtime_a):
    response = client.post("/api/admin/session/create", headers=tenant_a_auth)
    assert response.status_code == 201
    stored = session_manager.resolve_customer_session(response.json()["session_id"])
    assert stored.tenant_id == "tenant-a"


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/admin/session/{id}"),
    ("GET", "/api/admin/session/{id}/messages"),
    ("DELETE", "/api/admin/session/{id}/terminate"),
])
def test_tenant_a_cannot_observe_tenant_b(client, tenant_a_auth, tenant_b_session, method, path):
    response = client.request(method, path.format(id=tenant_b_session.id), headers=tenant_a_auth)
    assert response.status_code == 404
    assert response.json() == {"detail": "Session not found"}


def test_customer_capability_with_mismatched_bearer_cannot_downgrade(client, tenant_a_auth, tenant_b_session):
    response = client.get(
        f"/api/customer/session/{tenant_b_session.id}", headers=tenant_a_auth
    )
    assert response.status_code == 404


def test_runtime_configuration_is_never_reused_between_tenants(
    client, tenant_a_auth, tenant_b_auth, runtime_a, runtime_b
):
    created_a = client.post("/api/admin/session/create", headers=tenant_a_auth).json()
    created_b = client.post("/api/admin/session/create", headers=tenant_b_auth).json()
    key_a = TenantSessionKey("tenant-a", created_a["session_id"])
    key_b = TenantSessionKey("tenant-b", created_b["session_id"])
    assert session_manager.get_session(key_a).runtime_configuration == (
        RuntimeConfigurationSnapshot.from_configuration(runtime_a)
    )
    assert session_manager.get_session(key_b).runtime_configuration == (
        RuntimeConfigurationSnapshot.from_configuration(runtime_b)
    )
```

- [ ] **Step 2: Run boundary tests and verify cross-tenant requests currently succeed**

Run: `pytest -q tests/test_tenant_session_access.py tests/test_auth.py services/api_gateway/tests/test_admin.py services/api_gateway/tests/test_customer.py`

Expected: FAIL because admin handlers discard `StudioTenantContext` and customer handlers perform global lookups.

- [ ] **Step 3: Implement fail-closed access dependencies and role-specific session routes**

```python
def require_admin_session_key(
    session_id: str,
    context: Annotated[StudioTenantContext, Depends(require_studio_tenant_context)],
) -> TenantSessionKey:
    key = TenantSessionKey(context.tenant_id, session_id)
    if session_manager.get_session(key) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return key


def require_customer_session_key(
    session_id: str,
    principal: Annotated[dict[str, Any] | None, Depends(optional_ssf_user)],
) -> TenantSessionKey:
    key = session_manager.resolve_customer_session(session_id)
    if key is None or (principal is not None and principal["studio_tenant_id"] != key.tenant_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return key
```

`POST /api/admin/session/create` depends on `ValidatedRuntimeConfiguration`, verifies context/config tenant and authorization revision, builds `RuntimeConfigurationSnapshot`, and then creates state. Move customer status to `GET /api/customer/session/{session_id}`. Remove `/api/session/create`, `/api/session/{session_id}`, and `/api/sessions/active` from the production router. Update `tests/conftest.py` to override `require_studio_tenant_context` and `require_validated_runtime_configuration` explicitly instead of bypassing `require_ssf_user` globally.

Both admin and customer status responses expose `warning_at` and `timeout_at`
as ISO-8601 timestamps. They expose no tenant ID or runtime-configuration
payload.

- [ ] **Step 4: Run admin/customer/auth route tests**

Run: `pytest -q tests/test_tenant_session_access.py tests/test_auth.py services/api_gateway/tests/test_admin.py services/api_gateway/tests/test_customer.py tests/test_session_route_coverage.py`

Expected: PASS and OpenAPI contains no generic session-management routes.

- [ ] **Step 5: Commit HTTP tenant enforcement**

```bash
git add services/api_gateway/session_access.py services/api_gateway/auth.py services/api_gateway/routes/admin.py services/api_gateway/routes/customer.py services/api_gateway/routes/session.py services/api_gateway/app.py tests/conftest.py tests/test_tenant_session_access.py tests/test_auth.py services/api_gateway/tests/test_admin.py services/api_gateway/tests/test_customer.py tests/test_session_route_coverage.py
git commit -m "feat: enforce tenant session access"
```

### Task 5: Isolate message processing and audio artifacts by tenant and role

**Files:**
- Create: `services/api_gateway/conversation_service.py`
- Modify: `services/api_gateway/audio_storage.py`
- Modify: `services/api_gateway/routes/admin.py`
- Modify: `services/api_gateway/routes/customer.py`
- Rewrite: `services/api_gateway/routes/session.py`
- Create: `tests/test_tenant_audio_storage.py`
- Create: `tests/test_tenant_message_routes.py`
- Modify: `tests/test_unified_message_endpoint.py`
- Modify: `tests/test_audio_service_behavior.py`
- Modify: `tests/test_pipeline_metadata_enhancement.py`
- Modify: `tests/test_sonar_new_coverage_audio.py`

**Interfaces:**
- Consumes: authorized `TenantSessionKey` dependencies from Task 4.
- Produces: `ConversationService.process_text(key, sender, request)` and `.process_audio(key, sender, upload)`; callers supply a server-assigned `ClientType` constant.
- Produces: `save_audio(key, message_id, variant, data) -> None` and `audio_path(key, message_id, variant) -> Path`.

- [ ] **Step 1: Write failing role-spoofing, path-isolation, and ownership tests**

```python
def test_audio_path_contains_pseudonymous_tenant_and_session(tmp_path):
    key = TenantSessionKey("tenant-a", "ABC12345")
    path = audio_path(key, "msg-1", AudioVariant.ORIGINAL, base_dir=tmp_path)
    assert path == tmp_path / "v2" / key.tenant_ref / "ABC12345" / "original" / "msg-1.wav"
    assert "tenant-a" not in str(path)


def test_admin_message_ignores_client_role_field(client, tenant_a_auth, tenant_a_session):
    response = client.post(
        f"/api/admin/session/{tenant_a_session.id}/message",
        headers=tenant_a_auth,
        json={"text": "Hallo", "source_lang": "de", "target_lang": "en", "client_type": "customer"},
    )
    assert response.status_code == 200
    assert session_manager.get_session(tenant_a_session.key).messages[-1].sender is ClientType.ADMIN


def test_audio_lookup_requires_message_ownership(client, tenant_a_auth, tenant_a_session, tenant_b_message):
    response = client.get(
        f"/api/admin/session/{tenant_a_session.id}/audio/{tenant_b_message.id}/translated.wav",
        headers=tenant_a_auth,
    )
    assert response.status_code == 404
```

- [ ] **Step 2: Run message/audio tests and verify legacy global paths fail them**

Run: `pytest -q tests/test_tenant_audio_storage.py tests/test_tenant_message_routes.py tests/test_unified_message_endpoint.py tests/test_audio_service_behavior.py tests/test_pipeline_metadata_enhancement.py tests/test_sonar_new_coverage_audio.py`

Expected: FAIL because `client_type` is trusted and audio lookup scans every session.

- [ ] **Step 3: Extract trusted processing and implement v2 audio storage**

```python
class AudioVariant(str, Enum):
    ORIGINAL = "original"
    TRANSLATED = "translated"


def audio_path(
    key: TenantSessionKey,
    message_id: str,
    variant: AudioVariant,
    *,
    base_dir: Path = AUDIO_BASE_DIR,
) -> Path:
    safe_session = require_storage_identifier(key.session_id)
    safe_message = require_storage_identifier(message_id)
    return base_dir / "v2" / key.tenant_ref / safe_session / variant.value / f"{safe_message}.wav"
```

Route wrappers set `sender=ClientType.ADMIN` or `sender=ClientType.CUSTOMER`; request models contain no `client_type`. Build response URLs only as `/api/{role}/session/{session_id}/audio/{message_id}/{variant}.wav`. Before opening a file, retrieve the authorized session and find the message in that session. Remove `/api/session/{id}/message`, `/api/session/{id}/messages`, `/api/audio/{message_id}.wav`, and `/api/audio/input_{message_id}.wav`.

- [ ] **Step 4: Run focused tests plus pipeline regressions**

Run: `pytest -q tests/test_tenant_audio_storage.py tests/test_tenant_message_routes.py tests/test_unified_message_endpoint.py tests/test_audio_service_behavior.py tests/test_pipeline_metadata_enhancement.py tests/test_sonar_new_coverage_audio.py tests/test_text_pipeline.py tests/test_pipeline_metadata_integration.py tests/test_websocket_sender_exclusion.py`

Expected: PASS.

- [ ] **Step 5: Commit tenant-isolated messages and audio**

```bash
git add services/api_gateway/conversation_service.py services/api_gateway/audio_storage.py services/api_gateway/routes/admin.py services/api_gateway/routes/customer.py services/api_gateway/routes/session.py tests/test_tenant_audio_storage.py tests/test_tenant_message_routes.py tests/test_unified_message_endpoint.py tests/test_audio_service_behavior.py tests/test_pipeline_metadata_enhancement.py tests/test_sonar_new_coverage_audio.py
git commit -m "feat: isolate tenant messages and audio"
```

### Task 6: Add short-lived single-use admin realtime tickets

**Files:**
- Create: `services/api_gateway/realtime_ticket.py`
- Modify: `services/api_gateway/routes/admin.py`
- Create: `tests/test_realtime_ticket.py`
- Create: `tests/test_admin_realtime_ticket_route.py`

**Interfaces:**
- Consumes: authenticated `TenantSessionKey` from Task 4.
- Produces: `RealtimeTransportKind = Literal["websocket", "polling"]`.
- Produces: `RealtimeTicketStore.issue(key, transport, ttl_seconds=60) -> IssuedRealtimeTicket` and `.consume(raw_ticket, key, transport) -> bool`.
- Produces: `POST /api/admin/session/{session_id}/realtime-ticket` with `{ "transport": "websocket" | "polling" }`.

- [ ] **Step 1: Write failing issuance, expiry, replay, and scope tests**

```python
def test_ticket_is_hashed_scoped_and_single_use(ticket_store, key_a, key_b):
    issued = ticket_store.issue(key_a, "websocket", ttl_seconds=60)
    assert issued.ticket not in ticket_store.redis.dump_values()
    assert ticket_store.consume(issued.ticket, key_b, "websocket") is False
    assert ticket_store.consume(issued.ticket, key_a, "polling") is False
    assert ticket_store.consume(issued.ticket, key_a, "websocket") is True
    assert ticket_store.consume(issued.ticket, key_a, "websocket") is False


def test_admin_cannot_issue_ticket_for_other_tenant(client, tenant_a_auth, tenant_b_session):
    response = client.post(
        f"/api/admin/session/{tenant_b_session.id}/realtime-ticket",
        headers=tenant_a_auth,
        json={"transport": "websocket"},
    )
    assert response.status_code == 404
```

- [ ] **Step 2: Run ticket tests and verify the module and route are absent**

Run: `pytest -q tests/test_realtime_ticket.py tests/test_admin_realtime_ticket_route.py`

Expected: FAIL during import or return 404 for the issuance route.

- [ ] **Step 3: Implement opaque issuance and atomic hash consumption**

```python
def _ticket_hash(ticket: str) -> str:
    return sha256(ticket.encode("ascii")).hexdigest()

def issue(self, key: TenantSessionKey, transport: RealtimeTransportKind, ttl_seconds: int = 60):
    ticket = secrets.token_urlsafe(32)
    payload = json.dumps({
        "tenant_id": key.tenant_id,
        "session_id": key.session_id,
        "role": "admin",
        "transport": transport,
    }, sort_keys=True, separators=(",", ":"))
    redis_key = f"{self.namespace}:v2:realtime-ticket:{_ticket_hash(ticket)}"
    if not self.redis.set(redis_key, payload, ex=ttl_seconds, nx=True):
        raise RealtimeTicketUnavailable()
    return IssuedRealtimeTicket(ticket=ticket, expires_at=self.clock() + timedelta(seconds=ttl_seconds))
```

Consume with one Lua script that `GET`s and `DEL`s the hash key atomically, then compare all four payload fields. Scope mismatch consumes the ticket and returns false. Redis errors return HTTP 503; raw tickets and payload identity values never enter logs.

- [ ] **Step 4: Run ticket and log-safety tests**

Run: `pytest -q tests/test_realtime_ticket.py tests/test_admin_realtime_ticket_route.py tests/test_log_safety.py`

Expected: PASS.

- [ ] **Step 5: Commit the admin realtime capability**

```bash
git add services/api_gateway/realtime_ticket.py services/api_gateway/routes/admin.py tests/test_realtime_ticket.py tests/test_admin_realtime_ticket_route.py
git commit -m "feat: add scoped realtime tickets"
```

### Task 7: Key WebSocket, polling, and monitoring state by tenant

**Files:**
- Modify: `services/api_gateway/websocket.py`
- Modify: `services/api_gateway/websocket_monitor.py`
- Rewrite: `services/api_gateway/websocket_polling_routes.py`
- Modify: `services/api_gateway/websocket_fallback.py`
- Modify: `services/api_gateway/websocket_monitoring_routes.py`
- Modify: `services/api_gateway/routes/admin.py`
- Modify: `services/api_gateway/routes/customer.py`
- Modify: `services/api_gateway/app.py`
- Create: `tests/test_tenant_websocket.py`
- Create: `tests/test_tenant_polling.py`
- Modify: `tests/test_websocket_manager.py`
- Modify: `tests/test_websocket_polling_behavior.py`
- Modify: `tests/test_websocket_polling_coverage.py`

**Interfaces:**
- Consumes: `TenantSessionKey`, customer resolution, and single-use tickets.
- Produces: `WS /ws/admin/{session_id}?ticket=<opaque-ticket>` and `WS /ws/customer/{session_id}`.
- Produces: admin polling routes below `/api/admin/session/{session_id}/polling` and customer polling routes below `/api/customer/session/{session_id}/polling`; their stored `PollingClient` contains the resolved key and server-assigned role.
- Produces: tenant-scoped admin monitoring routes; installation health and aggregate counters remain global.

- [ ] **Step 1: Write failing duplicate-ID isolation and handshake tests**

```python
@pytest.mark.asyncio
async def test_same_session_id_in_two_tenants_never_cross_broadcast(manager, sockets):
    key_a = TenantSessionKey("tenant-a", "DUPL1234")
    key_b = TenantSessionKey("tenant-b", "DUPL1234")
    await manager.connect_websocket(sockets.a, key_a, ClientType.ADMIN)
    await manager.connect_websocket(sockets.b, key_b, ClientType.ADMIN)
    await manager.broadcast_to_session(key_a, {"type": "message"})
    sockets.a.send_json.assert_awaited()
    sockets.b.send_json.assert_not_awaited()


def test_admin_websocket_rejects_ticket_before_accept(client, expired_ticket):
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(f"/ws/admin/ABC12345?ticket={expired_ticket}"):
            pass
    assert closed.value.code == 4404
```

Also prove customer join resolution, admin ticket replay rejection, polling-ID tenant/role binding, tenant-scoped monitoring, termination cleanup, sender exclusion, and fallback queue isolation.

- [ ] **Step 2: Run realtime tests and verify registries collide on session ID**

Run: `pytest -q tests/test_tenant_websocket.py tests/test_tenant_polling.py tests/test_websocket_manager.py tests/test_websocket_polling_behavior.py tests/test_websocket_polling_coverage.py`

Expected: FAIL because registries and fallback clients retain only `session_id` plus client-controlled role.

- [ ] **Step 3: Refactor every realtime registry and route to retain the full key**

```python
self.session_connections: dict[TenantSessionKey, dict[str, WebSocketConnection]] = {}

@dataclass
class WebSocketConnection:
    websocket: WebSocket
    key: TenantSessionKey
    client_type: ClientType
    # existing heartbeat and adaptive-polling fields remain

@dataclass
class PollingClient:
    polling_id: str
    key: TenantSessionKey
    client_type: ClientType
    # existing queue, timing, and recovery fields remain
```

Validate the admin ticket and customer capability before `websocket.accept()`. Make `_build_connection_id` use `key.tenant_ref`, `key.session_id`, server-assigned role, and randomness. Change broadcast, disconnect, heartbeat, timeout warning, termination, fallback delivery, queue lookup, and monitor lookup signatures from `session_id` to `TenantSessionKey`. Remove `WS /ws/{session_id}/{client_type}` and generic `/api/websocket/polling/**` activation that accepts `client_type`.

Use these exact polling contracts:

```text
POST   /api/admin/session/{session_id}/polling/activate
GET    /api/admin/session/{session_id}/polling/{polling_id}
POST   /api/admin/session/{session_id}/polling/{polling_id}/send
GET    /api/admin/session/{session_id}/polling/{polling_id}/status
POST   /api/admin/session/{session_id}/polling/{polling_id}/recover
DELETE /api/admin/session/{session_id}/polling/{polling_id}

POST   /api/customer/session/{session_id}/polling/activate
GET    /api/customer/session/{session_id}/polling/{polling_id}
POST   /api/customer/session/{session_id}/polling/{polling_id}/send
GET    /api/customer/session/{session_id}/polling/{polling_id}/status
POST   /api/customer/session/{session_id}/polling/{polling_id}/recover
DELETE /api/customer/session/{session_id}/polling/{polling_id}
```

Admin activation consumes a ticket issued for transport `polling`; customer
activation resolves the public capability. The route determines the role, and
every later operation verifies both path session and stored `TenantSessionKey`.
Move tenant-scoped monitoring to `GET /api/admin/realtime/connections` and
`GET /api/admin/session/{session_id}/realtime/connections`; retain only the
aggregate health and Prometheus endpoints outside `/api/admin`.

- [ ] **Step 4: Run the complete realtime regression set**

Run: `pytest -q tests/test_tenant_websocket.py tests/test_tenant_polling.py tests/test_websocket_manager.py tests/test_websocket_connection_identity.py tests/test_websocket_sender_exclusion.py tests/test_websocket_polling_behavior.py tests/test_websocket_polling_coverage.py tests/test_websocket_polling_queue_overflow.py tests/test_websocket_disconnect_reasons.py tests/test_websocket_close_code_classification.py`

Expected: PASS.

- [ ] **Step 5: Commit tenant-isolated realtime state**

```bash
git add services/api_gateway/websocket.py services/api_gateway/websocket_monitor.py services/api_gateway/websocket_polling_routes.py services/api_gateway/websocket_fallback.py services/api_gateway/websocket_monitoring_routes.py services/api_gateway/routes/admin.py services/api_gateway/routes/customer.py services/api_gateway/app.py tests/test_tenant_websocket.py tests/test_tenant_polling.py tests/test_websocket_manager.py tests/test_websocket_polling_behavior.py tests/test_websocket_polling_coverage.py
git commit -m "feat: isolate tenant realtime channels"
```

### Task 8: Update the frontend to use role-specific contracts and admin tickets

**Files:**
- Modify: `services/frontend/src/core/http/client.ts`
- Modify: `services/frontend/src/domain/admin/admin.repository.ts`
- Modify: `services/frontend/src/domain/session/session.repository.ts`
- Modify: `services/frontend/src/domain/message/message.repository.ts`
- Modify: `services/frontend/src/core/realtime/realtime.port.ts`
- Modify: `services/frontend/src/core/realtime/WebSocketTransport.ts`
- Modify: `services/frontend/src/app/providers/services.ts`
- Modify: `services/frontend/src/features/conversation/useConversation.ts`
- Modify: `services/frontend/src/domain/admin/__tests__/admin.test.ts`
- Modify: `services/frontend/src/domain/session/__tests__/session.test.ts`
- Modify: `services/frontend/src/domain/message/__tests__/message.repository.test.ts`
- Modify: `services/frontend/src/core/realtime/__tests__/WebSocketTransport.test.ts`
- Modify: `services/frontend/src/features/admin/__tests__/adminSessionFlow.test.tsx`

**Interfaces:**
- Consumes: role-specific HTTP and WebSocket contracts from Tasks 4–7.
- Produces: `AdminRepository.issueRealtimeTicket(sessionId, transport)` and async `RealtimeTransport.connect(sessionId, role): Promise<void>`.
- Removes: periodic `SessionRepository.reportActivity`; socket presence now controls grace timing.

- [ ] **Step 1: Write failing repository and transport contract tests**

```typescript
it('uses role-specific message routes without sending client_type', async () => {
  await repository.sendText('ABC12345', {
    text: 'Hallo', sourceLanguage: 'de', targetLanguage: 'en', role: 'admin'
  });
  expect(http.post).toHaveBeenCalledWith(
    '/api/admin/session/ABC12345/message',
    { text: 'Hallo', source_lang: 'de', target_lang: 'en' },
    expect.any(Object)
  );
});

it('fetches a fresh admin ticket for every reconnect and never places the JWT in the URL', async () => {
  await transport.connect('ABC12345', 'admin');
  sockets[0].close();
  await vi.runOnlyPendingTimersAsync();
  expect(issueTicket).toHaveBeenCalledTimes(2);
  expect(socketUrls[0]).toMatch('/ws/admin/ABC12345?ticket=');
  expect(socketUrls.join('')).not.toContain('eyJ');
});
```

- [ ] **Step 2: Run frontend tests and verify legacy URL expectations fail**

Run: `npm --prefix services/frontend test -- src/domain src/core/realtime src/features/admin/__tests__/adminSessionFlow.test.tsx`

Expected: FAIL because repositories still call `/api/session/**`, submit `client_type`, and construct `/ws/{id}/{role}` directly.

- [ ] **Step 3: Implement role-derived URLs and asynchronous ticketed reconnect**

```typescript
export interface RealtimeTransport {
  connect(sessionId: string, role: ClientRole): Promise<void>;
  disconnect(): void;
  send(payload: Record<string, unknown>): void;
  onEvent(handler: (event: RealtimeEvent) => void): () => void;
  onStatus(handler: (status: RealtimeStatus) => void): () => void;
  getStatus(): RealtimeStatus;
}

const pathForRole = (role: ClientRole, sessionId: string) =>
  `/api/${role}/session/${requirePathIdentifier(sessionId, 'session')}`;
```

The HTTP interceptor attaches bearer tokens only to `/api/admin/**` and removes the legacy-access header branch. Admin socket open and every reconnect await `issueRealtimeTicket(id, "websocket")`; customer sockets use `/ws/customer/{id}`. Guard async ticket completion with a connection generation counter so a ticket returned after `disconnect()` cannot open a socket. Remove the 30-second `reportActivity` interval from `useConversation`.

- [ ] **Step 4: Run frontend tests, lint, and production build**

Run: `npm --prefix services/frontend test && npm --prefix services/frontend run lint && npm --prefix services/frontend run build`

Expected: all commands PASS.

- [ ] **Step 5: Commit the frontend contract migration**

```bash
git add services/frontend/src
git commit -m "feat(frontend): use tenant-isolated conversation APIs"
```

### Task 9: Pseudonymize tenant telemetry and scope administrative monitoring

**Files:**
- Modify: `services/api_gateway/quality_telemetry.py`
- Modify: `services/api_gateway/session_pseudonym.py`
- Modify: `services/api_gateway/log_safety.py`
- Modify: `services/api_gateway/session_manager.py`
- Modify: `services/api_gateway/websocket_monitor.py`
- Modify: `services/api_gateway/websocket_monitoring_routes.py`
- Modify: `tests/test_session_lifecycle_emission.py`
- Create: `tests/test_tenant_log_safety.py`
- Modify: `services/api_gateway/tests/test_metrics.py`

**Interfaces:**
- Consumes: `TenantSessionKey.tenant_ref`.
- Produces: structured lifecycle/security events containing bounded pseudonymous `tenant_ref` only where correlation is needed.
- Produces: admin connection listing filtered by authenticated tenant; global health and Prometheus metrics contain no tenant/session labels.

- [ ] **Step 1: Write failing leak and metric-cardinality tests**

```python
def test_cross_tenant_denial_log_contains_only_tenant_ref(caplog):
    deny_cross_tenant(TenantSessionKey("secret-tenant", "ABC12345"))
    assert "secret-tenant" not in caplog.text
    assert "ABC12345" not in caplog.text
    assert sha256(b"secret-tenant").hexdigest()[:12] in caplog.text


def test_prometheus_output_has_no_tenant_or_session_labels(client):
    output = client.get("/metrics").text
    assert "tenant_id=" not in output
    assert "tenant_ref=" not in output
    assert "session_id=" not in output
```

- [ ] **Step 2: Run telemetry tests and identify raw identifier leaks**

Run: `pytest -q tests/test_tenant_log_safety.py tests/test_session_lifecycle_emission.py services/api_gateway/tests/test_metrics.py`

Expected: FAIL on raw session logging and missing tenant-scoped monitoring behavior.

- [ ] **Step 3: Pass pseudonymous structured fields through lifecycle and monitoring code**

```python
logger.info(
    "session_created",
    extra={"tenant_ref": key.tenant_ref, "session_ref": session_ref(key.session_id)},
)
```

Replace interpolated raw identifiers, URLs, filesystem paths, ticket values, and exception strings in changed conversation paths with fixed event names and allowlisted fields. Filter admin monitoring by `StudioTenantContext.tenant_id` before serialization. Keep Prometheus outcomes such as `accepted`, `not_found`, `expired`, and `scope_mismatch` as fixed label values without an identity label.

- [ ] **Step 4: Run telemetry tests and scan changed backend code**

Run: `pytest -q tests/test_tenant_log_safety.py tests/test_session_lifecycle_emission.py services/api_gateway/tests/test_metrics.py && rg -n 'logger\.(info|warning|error|exception).*tenant_id|logger\.(info|warning|error|exception).*session_id' services/api_gateway`

Expected: tests PASS; every remaining scan hit is either a fixed field name without a raw value or is removed before commit.

- [ ] **Step 5: Commit telemetry isolation**

```bash
git add services/api_gateway/quality_telemetry.py services/api_gateway/session_pseudonym.py services/api_gateway/log_safety.py services/api_gateway/session_manager.py services/api_gateway/websocket_monitor.py services/api_gateway/websocket_monitoring_routes.py tests/test_session_lifecycle_emission.py tests/test_tenant_log_safety.py services/api_gateway/tests/test_metrics.py
git commit -m "fix: pseudonymize tenant conversation telemetry"
```

### Task 10: Add the guarded destructive production cutover

**Files:**
- Create: `services/api_gateway/tenant_cutover.py`
- Create: `scripts/reset-legacy-conversation-state.sh`
- Create: `tests/test_tenant_cutover.py`
- Modify: `tests/operations/test_production_scripts.py`
- Modify: `tests/operations/test_production_compose.py`
- Modify: `deploy/production/docker-compose.production.yml`
- Modify: `deploy/production/production.env.example`
- Modify: `.env.example`
- Create: `docs/operations/runbooks/tenant-isolation-cutover.md`

**Interfaces:**
- Produces: `python -m services.api_gateway.tenant_cutover --dry-run|--apply --confirm-empty-production`.
- Produces: `scripts/reset-legacy-conversation-state.sh --destructive-reset-production` which refuses to run while gateway or frontend containers are active.
- Consumes/deletes only legacy Redis session keys and the legacy audio `original/` and `translated/` directories.

- [ ] **Step 1: Write failing allowlist, refusal, dry-run, and idempotency tests**

```python
def test_cutover_removes_only_legacy_conversation_state(fake_redis, audio_root):
    seed_legacy_sessions(fake_redis, ["ABC12345"])
    fake_redis.set("unrelated:key", "keep")
    (audio_root / "original" / "input-msg.wav").write_bytes(b"wav")
    result = cutover(fake_redis, audio_root, apply=True, confirmed=True)
    assert result.redis_keys_deleted == 3
    assert fake_redis.get("unrelated:key") == "keep"
    assert not (audio_root / "original").exists()
    assert cutover(fake_redis, audio_root, apply=True, confirmed=True).redis_keys_deleted == 0


def test_shell_wrapper_refuses_running_gateway(fake_docker):
    fake_docker.running_services = {"api_gateway"}
    result = run_script("scripts/reset-legacy-conversation-state.sh", "--destructive-reset-production")
    assert result.returncode == 1
    assert "api_gateway is still running" in result.stderr
```

- [ ] **Step 2: Run cutover tests and verify command absence**

Run: `pytest -q tests/test_tenant_cutover.py tests/operations/test_production_scripts.py tests/operations/test_production_compose.py`

Expected: FAIL because the guarded reset command and timeout environment entries do not exist.

- [ ] **Step 3: Implement exact-target deletion and production settings**

```python
LEGACY_EXACT_KEYS = ("{namespace}:sessions", "{namespace}:session:active_admin")
LEGACY_SESSION_PREFIX = "{namespace}:session:"
LEGACY_AUDIO_DIRS = ("original", "translated")
```

Use Redis `SCAN` with the exact legacy prefix, exclude all `ssf:v2:*` keys, validate every candidate before deletion, and use batched `UNLINK`. Resolve audio targets and require their parents to equal the configured audio root; refuse symlinks or `/`. Dry-run prints only counts and target categories, not session IDs. The shell wrapper checks `production_compose ps --status running --services`, then invokes a one-off gateway container so the mounted Redis and audio volumes are the production volumes.

Add exact production values:

```text
SSF_ENABLE_LEGACY_ADMIN_ACCESS=false
SSF_SESSION_RECONNECT_GRACE_MINUTES=30
SSF_SESSION_TIMEOUT_WARNING_MINUTES=5
SSF_SESSION_MAX_HOURS=8
```

The runbook sequence is: build reviewed immutable images; validate two Studio/Keycloak tenants; stop gateway and frontend; run the destructive reset; start v2 images; run health plus two-tenant smoke. Rollback restores previous immutable images but does not restore discarded conversations.

- [ ] **Step 4: Run operations tests and shell validation**

Run: `pytest -q tests/test_tenant_cutover.py tests/operations/test_production_scripts.py tests/operations/test_production_compose.py && bash -n scripts/reset-legacy-conversation-state.sh && docker compose -f deploy/production/docker-compose.production.yml config --quiet --no-interpolate`

Expected: PASS without interpolating production secrets.

- [ ] **Step 5: Commit the destructive cutover tooling**

```bash
git add services/api_gateway/tenant_cutover.py scripts/reset-legacy-conversation-state.sh tests/test_tenant_cutover.py tests/operations/test_production_scripts.py tests/operations/test_production_compose.py deploy/production/docker-compose.production.yml deploy/production/production.env.example .env.example docs/operations/runbooks/tenant-isolation-cutover.md
git commit -m "feat(ops): add tenant isolation cutover"
```

### Task 11: Prove the complete two-tenant boundary and close the approved OpenSpec scope

**Files:**
- Create: `tests/integration/test_tenant_isolation_matrix.py`
- Create: `scripts/tenant-isolation-smoke.py`
- Create: `tests/operations/test_tenant_isolation_smoke.py`
- Modify: `openspec/changes/add-multi-tenant-operations/tasks.md`
- Modify: `docs/superpowers/specs/2026-09-11-tenant-isolation-design.md` only if implementation discovered a concrete contract correction.

**Interfaces:**
- Consumes: all tenant-isolated REST, audio, realtime, polling, monitoring, timeout, and cutover contracts.
- Produces: an automated A-to-B negative matrix and a production smoke command driven by `SSF_TENANT_A_TOKEN`, `SSF_TENANT_B_TOKEN`, and `SSF_SMOKE_BASE_URL` without printing credentials.

- [ ] **Step 1: Write the full integration matrix before final implementation cleanup**

```python
PROTECTED_OPERATIONS = (
    "current", "history", "status", "terminate", "messages_read",
    "messages_write", "audio_original", "audio_translated",
    "websocket", "polling", "monitoring",
)

@pytest.mark.parametrize("operation", PROTECTED_OPERATIONS)
def test_tenant_a_cannot_access_tenant_b(two_tenant_system, operation):
    response = two_tenant_system.perform(
        operation, actor="tenant-a", resource="tenant-b"
    )
    assert response.status_code == 404
    assert response.public_error == "Session not found"


def test_positive_flows_remain_independent(two_tenant_system):
    a = two_tenant_system.complete_conversation("tenant-a")
    b = two_tenant_system.complete_conversation("tenant-b")
    assert a.session_id != b.session_id
    assert a.messages == ["tenant-a-message"]
    assert b.messages == ["tenant-b-message"]
```

Include tests for same-ID malformed fixtures, customer `/join/:sessionId`, runtime-configuration snapshots, 30-minute reconnect grace, five-minute warning, eight-hour maximum, ticket replay, and cleanup isolation.

- [ ] **Step 2: Run the matrix and fix only concrete failures through their owning modules**

Run: `pytest -q tests/integration/test_tenant_isolation_matrix.py tests/operations/test_tenant_isolation_smoke.py`

Expected: PASS. For each failure, first add a focused regression test beside the owning module, observe it fail, apply the smallest fix, and rerun the focused test before rerunning this matrix.

- [ ] **Step 3: Implement a credential-safe production smoke client**

```python
def main() -> int:
    settings = SmokeSettings.from_environment()
    with httpx.Client(base_url=settings.base_url, timeout=20) as client:
        session_a = create_session(client, settings.tenant_a_token)
        session_b = create_session(client, settings.tenant_b_token)
        assert_cross_tenant_404(client, settings.tenant_a_token, session_b)
        assert_cross_tenant_404(client, settings.tenant_b_token, session_a)
        assert_customer_join(client, session_a)
        terminate_session(client, settings.tenant_a_token, session_a)
        terminate_session(client, settings.tenant_b_token, session_b)
    print("Tenant isolation smoke passed")
    return 0
```

Use existing HTTP dependencies already locked by the project; do not add token values to exceptions, argparse output, logs, or test snapshots. The script is non-destructive beyond sessions it creates itself and terminates them in `finally`.

- [ ] **Step 4: Run all verification gates and update only completed OpenSpec items**

Run:

```bash
pytest -q
npm --prefix services/frontend test
npm --prefix services/frontend run lint
npm --prefix services/frontend run build
pre-commit run --all-files
openspec validate add-multi-tenant-operations --strict
git diff --check
```

Expected: every command PASS. Then mark OpenSpec tasks `1.3`, `2.1`, `2.2`, `2.3`, and `2.4` complete. Leave legal review, control-plane lifecycle, pilot, and regular-operation tasks unchecked because this implementation does not prove them.

- [ ] **Step 5: Commit the isolation proof and OpenSpec status**

```bash
git add tests/integration/test_tenant_isolation_matrix.py scripts/tenant-isolation-smoke.py tests/operations/test_tenant_isolation_smoke.py openspec/changes/add-multi-tenant-operations/tasks.md docs/superpowers/specs/2026-09-11-tenant-isolation-design.md
git commit -m "test: prove tenant conversation isolation"
```

- [ ] **Step 6: Request code review before merge and production cutover**

Run: `git status --short && git log --oneline --decorate --max-count=15`

Expected: clean worktree and one reviewable commit per task. Use the `requesting-code-review` skill, resolve findings with the `receiving-code-review` skill, rerun Step 4, merge reviewed immutable images, and execute `docs/operations/runbooks/tenant-isolation-cutover.md` exactly.
