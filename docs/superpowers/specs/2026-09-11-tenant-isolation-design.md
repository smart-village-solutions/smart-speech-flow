# Tenant-Isolated Conversation Operations Design

## Context

The Studio-backed tenant login directory establishes a trustworthy tenant
identity for administrative users. It does not yet isolate SSF conversations:
the current session manager, Redis keys, messages, audio files, WebSocket
registries, and polling registries are keyed only by public session or message
identifiers.

Production currently has no active users or conversations. The rollout may
therefore use a destructive cutover: all legacy sessions, messages, realtime
state, and audio artifacts are discarded. No legacy data migration or
compatibility layer is required.

This design implements the technical-isolation portion of OpenSpec change
`add-multi-tenant-operations`. Studio remains the source of administrative
tenant identity, and the public customer link remains `/join/:sessionId`.

## Goals

- Bind every administrative conversation operation to the tenant from the
  validated Keycloak token.
- Isolate sessions, messages, audio, runtime configuration, realtime
  connections, polling state, and administrative monitoring between tenants.
- Keep the public customer link unchanged and derive its tenant exclusively
  from server-owned session state.
- Reject cross-tenant access without revealing whether another tenant owns the
  requested resource.
- Preserve natural pauses while an administrator remains connected.
- Provide deterministic destructive cutover and rollback procedures.
- Prove isolation with positive and cross-tenant negative tests for two tenants.

## Non-goals

- Migrating or preserving existing sessions, messages, realtime state, or audio.
- Adding billing, tenant self-service, branding, model selection, or a new
  administration UI.
- Passing a tenant selector in a path, query, header, cookie, or request body.
- Running a separate SSF deployment or database per tenant.
- Changing the public route shape `/join/:sessionId`.

## Agreed constraints

- The cutover is destructive and does not preserve the current empty server
  state.
- Internal REST, audio, WebSocket, and polling contracts may change without a
  compatibility period.
- Administrative tenant identity comes only from `StudioTenantContext` derived
  from a validated bearer token.
- A public session ID is a customer invitation capability. It is not an
  administrative tenant selector.
- Keycloak JWTs are never placed in WebSocket URLs.
- `SSF_ENABLE_LEGACY_ADMIN_ACCESS` is `false` when tenant-isolated operations are
  enabled.

## Architecture decision

Use one explicitly tenant-aware conversation core rather than a manager registry
or a deployment per tenant. A frozen value object identifies an administrative
resource:

```python
@dataclass(frozen=True)
class TenantSessionKey:
    tenant_id: str
    session_id: str
```

`Session.tenant_id` is mandatory. Administrative APIs and internal services use
`TenantSessionKey`; public customer entry first resolves the opaque session ID
through a server-owned join index and then uses the same key internally.

This approach keeps background jobs, persistence, and connection management in
one process while making tenant scope explicit at every access boundary. A
per-tenant manager registry would complicate global customer-link resolution and
background jobs. Separate deployments would add disproportionate operational
cost and contradict the shared-instance architecture.

## Trust and access model

### Administrative access

Every `/api/admin/**` handler receives `StudioTenantContext` directly through
`require_studio_tenant_context`; router-level authentication without a returned
tenant value is insufficient. The handler constructs a `TenantSessionKey` from
the signed tenant ID and the requested session ID.

Creation, current-session lookup, history, status, termination, messages, audio,
realtime tickets, polling, and administrative monitoring all use this key. A
resource owned by another tenant is indistinguishable from a missing resource
and returns HTTP 404. The implementation never falls back to a global lookup
after a tenant-scoped miss.

### Customer access

The public route remains `/join/:sessionId`. A globally unique session ID is the
customer invitation capability. The server resolves it through a global join
index whose value is a `TenantSessionKey`; the browser cannot supply or override
the tenant ID.

Customer activation, status, message, audio, WebSocket, and polling operations
must resolve the key from that index. A missing, terminated, or inconsistent
entry fails closed. Supplying an administrative bearer token never downgrades to
customer capability access: if a bearer token is present, its tenant must match
the resolved session tenant.

Session-ID generation retains the public identifier format but checks the global
join index before accepting a candidate. Collision handling retries with a
bounded failure path rather than overwriting another tenant's entry.

### Role-specific contracts

Remove client-controlled role selection from protected operations. Replace the
shared message and realtime entrypoints with role-specific routes:

- `POST /api/admin/session/{session_id}/message`
- `GET /api/admin/session/{session_id}/messages`
- `POST /api/customer/session/{session_id}/message`
- `GET /api/customer/session/{session_id}/messages`
- `GET /api/admin/session/{session_id}/audio/{message_id}/{variant}.wav`
- `GET /api/customer/session/{session_id}/audio/{message_id}/{variant}.wav`
- `WS /ws/admin/{session_id}?ticket=<opaque-ticket>`
- `WS /ws/customer/{session_id}`

`variant` is exactly `original` or `translated`. Each audio lookup verifies that
the message belongs to the resolved session before opening a file. Realtime
events derive their sender role from the route and verified access, never from a
client payload.

Legacy duplicate or generic routes that permit an untrusted `client_type` are
removed from the production router during the hard cut.

## Session state and persistence

### In-memory state

The session manager owns these conceptual indexes:

```python
sessions: dict[TenantSessionKey, Session]
join_index: dict[str, TenantSessionKey]
active_admin_sessions: dict[str, set[str]]
websocket_connections: dict[TenantSessionKey, ConnectionSet]
```

`SSF_ALLOW_PARALLEL_SESSIONS=false` limits active sessions per tenant, not across
the whole installation. Creating a session for tenant A never terminates a
session owned by tenant B. Timeout scans may iterate all sessions internally but
must preserve the full key when updating, warning, broadcasting, or terminating.

### Redis schema

All new state uses schema version `v2`. Tenant IDs are encoded with unpadded
URL-safe base64 before use in Redis keys so allowed punctuation cannot create
ambiguous separators.

```text
ssf:v2:tenant:<encoded-tenant>:session:<session-id>
ssf:v2:tenant:<encoded-tenant>:sessions
ssf:v2:tenant:<encoded-tenant>:active-admin
ssf:v2:join:<session-id>
ssf:v2:realtime-ticket:<ticket-hash>
```

The session payload also contains the canonical tenant ID. Loading validates
that the payload tenant matches the key namespace and the join index. Any
mismatch is quarantined from runtime access and logged without raw tenant or
session identifiers.

No code reads legacy `ssf:session:*`, `ssf:sessions`, or
`ssf:session:active_admin` keys after cutover. Administrative listing and
history query only the current tenant's set; they never use a global Redis scan.

Redis mutations that create or terminate a session update the session record,
tenant indexes, and join index atomically through a transaction or Lua script.

### Runtime configuration

Session creation requires the existing `ValidatedRuntimeConfiguration`. Its
tenant ID and authorization revision must match the authenticated
`StudioTenantContext` before any session state is created. The session stores
the configuration revision and an immutable snapshot of the full validated
runtime configuration so a later Studio change cannot mix two tenant
configurations inside one active conversation.

New configuration revisions apply to newly created sessions. Existing sessions
continue with their validated snapshot until termination. Any process-local or
Redis configuration cache is keyed by tenant ID, configuration revision, and
authorization revision; a tenant-agnostic "current configuration" cache is
forbidden. Customer rendering and processing obtain configuration only from
the resolved session snapshot and never perform a client-selected tenant
lookup.

## Messages and audio

Messages remain embedded in their owning session for this delivery. Every
message mutation and history read therefore begins with an authorized
`TenantSessionKey` lookup.

Audio is stored below a tenant- and session-specific root:

```text
/data/audio/v2/<tenant-ref>/<session-id>/original/<message-id>.wav
/data/audio/v2/<tenant-ref>/<session-id>/translated/<message-id>.wav
```

`tenant-ref` is a deterministic SHA-256 pseudonym, not a display name or raw
tenant ID. File helpers accept the resolved session key and message ID, construct
paths themselves, reject traversal, and verify session/message ownership.
Response URLs are constructed at the role-specific API boundary rather than
persisted as globally reusable paths in `SessionMessage`.

Cleanup traverses only the managed `v2` tree, applies the existing retention
period, and reports aggregate counts. Terminating a session invalidates access
immediately; physical files remain subject to retention unless the destructive
cutover or an explicit privacy deletion removes them earlier.

## Realtime and polling

### Administrative tickets

An authenticated administrator requests a ticket from:

```text
POST /api/admin/session/{session_id}/realtime-ticket
```

The response contains a cryptographically random opaque ticket with a maximum
60-second lifetime. Redis stores only its hash and binds it to the tenant,
session, role, and allowed transport. A WebSocket or polling activation consumes
the ticket exactly once. Reconnects request a new ticket through the
authenticated REST client. Tickets cannot be used for another tenant, session,
role, or transport.

### Customer connections

Customer WebSocket and polling activation resolve the tenant through the public
session capability and verify that the session is joinable. They never accept a
tenant selector. The resulting connection or polling ID stores the resolved
`TenantSessionKey` and server-assigned customer role.

### Registry isolation

WebSocket channels, broadcasts, connection cleanup, monitoring, polling queues,
and fallback recovery are keyed by `TenantSessionKey`. A broadcast for tenant A
cannot enumerate or deliver to tenant B even if a malformed test fixture creates
duplicate session IDs.

Administrative monitoring endpoints require a tenant context and return only
that tenant's connections. Installation-wide health metrics remain aggregate
operator data and expose no raw tenant IDs, session IDs, or unbounded tenant
labels.

## Pause, presence, and timeout behavior

Transport heartbeats mean that a participant is present; they are not business
conversation activity.

- A connected administrator keeps the conversation alive during an arbitrary
  speaking pause.
- When the last administrator connection disappears, a 30-minute reconnect
  grace period starts. Customer presence alone does not stop this timer.
- Reconnecting within the grace period resumes the existing session.
- Five minutes before automatic termination, a warning is sent to any connected
  client and exposed in the session status.
- Every session has an absolute maximum lifetime of eight hours, including
  continuously connected sessions.
- Automatic termination invalidates tickets, polling IDs, and realtime
  connections before persisting the terminal state.

The initial defaults are configured as:

```text
SSF_SESSION_RECONNECT_GRACE_MINUTES=30
SSF_SESSION_TIMEOUT_WARNING_MINUTES=5
SSF_SESSION_MAX_HOURS=8
```

The model stores presence and timeout state separately from message activity so
silence never appears as a disconnected participant.

## Error handling

- Missing or invalid administrative credentials: 401 or 403 under the existing
  authentication contract.
- Valid administrator requesting another tenant's resource: neutral 404.
- Unknown or expired customer session capability: neutral 404.
- Payload tenant/key/index mismatch: fail closed, quarantine the record, and
  emit a pseudonymous security event.
- Missing, expired, replayed, or scope-mismatched realtime ticket: reject the
  WebSocket before acceptance or return neutral 404 for polling activation.
- Redis failure during an atomic security-sensitive mutation: fail the request;
  do not partially create, move, or terminate a session.

Error bodies do not contain owner tenant IDs, realm names, filesystem paths, or
the existence of a cross-tenant resource.

## Logging and telemetry

Logs use `tenant_ref = sha256(tenant_id)[:12]` and the existing pseudonymous
session reference. Raw tenant IDs, display names, bearer tokens, join
capabilities, realtime tickets, and audio paths are never logged.

Lifecycle and security telemetry carry the bounded pseudonymous tenant
reference where correlation is required. Prometheus metrics remain aggregate or
use fixed-cardinality outcome/reason labels; they do not label series with raw
tenant or session identifiers.

## Destructive production cutover

Because the production server has no users, the cutover does not need a drain,
maintenance page, legacy migration, or data backup:

1. Merge and build immutable gateway and frontend images from the reviewed
   tenant-isolation commit.
2. Validate Studio directory readiness and Keycloak claims for two tenants.
3. Stop gateway and frontend containers.
4. Run an explicit, idempotent cutover command that deletes only the known
   legacy Redis session keys, in-process realtime state by stopping the gateway,
   and files below the legacy audio `original/` and `translated/` directories.
5. Set `SSF_ENABLE_LEGACY_ADMIN_ACCESS=false` and the three timeout settings.
6. Start the gateway and frontend with the `v2` schema.
7. Run the automated two-tenant negative suite and production smoke procedure.

The cutover command requires an explicit production-reset flag, prints exact
target counts before deletion, refuses to run while the gateway is active, and
does not flush Redis or delete unrelated volume data.

Rollback stops the new containers and restores the previous immutable images.
Both the forward and rollback application start empty; discarded conversation
data is not restored.

## Test strategy

### Core and persistence tests

- Tenant A and B may hold active sessions simultaneously when per-tenant
  parallel sessions are disabled.
- Creating a second session for A terminates only A's previous session.
- Every lookup, history, message, termination, timeout, and persistence method
  requires or returns the correct `TenantSessionKey`.
- Runtime configuration is validated against the administrative tenant before
  session creation, cached only with tenant and revision scope, and frozen per
  session.
- Redis keys and indexes are tenant-scoped and atomic; corrupted cross-tenant
  payload/index combinations fail closed.
- Session-ID collision retries never overwrite another tenant's join index.

### HTTP and capability tests

- A bearer token for tenant A cannot read, mutate, terminate, list messages, or
  fetch audio for tenant B.
- Cross-tenant attempts return the same 404 contract as unknown resources.
- Customer operations derive the tenant from the join index and reject request
  tenant selectors.
- A presented bearer token cannot downgrade to customer capability access.
- Message sender roles are server-assigned by role-specific routes.

### Realtime tests

- Administrative ticket issuance requires the session's tenant.
- Tickets expire, are single-use, and reject tenant/session/role/transport
  mismatch.
- Tenant A broadcasts, polling queues, reconnects, timeouts, and cleanup never
  touch tenant B.
- Customer connections resolve their tenant from the public session capability.

### Timeout tests

- A connected administrator survives more than 30 minutes without messages.
- Disconnect starts the reconnect grace period; reconnect cancels it.
- Customer-only presence does not prevent termination.
- Warning and termination occur at the configured boundaries.
- The eight-hour absolute lifetime terminates even a connected session.

### Cutover and production tests

- The reset command deletes only allowlisted legacy keys and audio directories,
  is idempotent, and refuses unsafe targets or a running gateway.
- No runtime code loads legacy session keys after cutover.
- Two provisioned realms pass positive flows independently.
- The complete A-to-B negative matrix covers session creation, current/history
  lookup, status, termination, messages, audio, WebSocket, polling, and
  monitoring.
- The unchanged `/join/:sessionId` and QR/manual-code customer flow pass after
  isolation.

## Acceptance criteria

- Every administrative read and write is scoped by the signed Studio tenant
  context.
- Sessions, messages, audio, runtime configuration, WebSocket connections,
  polling state, and administrative monitoring cannot cross tenant boundaries.
- Customer routes contain no client-selected tenant and preserve
  `/join/:sessionId`.
- Natural pauses remain active while an administrator is connected; disconnect
  and absolute-lifetime rules terminate deterministically.
- The destructive reset and rollback procedures are repeatable and cannot erase
  unrelated Redis or filesystem data.
- Automated positive and negative tests pass for at least two tenants before
  production traffic is enabled.
