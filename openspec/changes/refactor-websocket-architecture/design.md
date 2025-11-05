## Context

The Smart Speech Flow backend has grown organically and now suffers from architectural inconsistencies in its WebSocket message broadcasting system. Multiple WebSocketManager instances exist across modules, terminology is inconsistent (client vs. customer), and critical message delivery fails silently due to broadcasting to the wrong manager instance.

### Background
- System enables real-time bidirectional translation between admin staff and multilingual customers
- WebSocket connections handle message delivery with HTTP polling as fallback
- Current implementation has multiple singleton pattern violations
- E2E tests show 0% message delivery success despite "successful" API responses

### Constraints
- Must maintain backward compatibility with existing WebSocket clients
- Cannot break existing REST API contracts
- Must support 1000+ concurrent sessions
- Deployment requires zero-downtime migration
- All changes must be validated with E2E tests before production

### Stakeholders
- Development team: Needs clear architecture and debugging capability
- Operations team: Needs reliable metrics and simple troubleshooting
- End users: Need consistent sub-100ms message delivery latency

## Goals / Non-Goals

### Goals
1. **Single Source of Truth**: Exactly one WebSocketManager instance manages all connections
2. **Consistent Terminology**: Unambiguous naming throughout codebase (admin vs. customer)
3. **Visible Failures**: All broadcast failures logged with actionable error messages
4. **100% Message Delivery**: E2E tests pass with all messages delivered successfully
5. **Comprehensive Documentation**: Architecture diagrams, API conventions, and troubleshooting guides

### Non-Goals
- Complete WebSocket protocol rewrite (use existing FastAPI WebSocket support)
- Migration to different message broker (Redis, RabbitMQ) - consider post-refactor
- Real-time scaling beyond current capacity (1000 sessions sufficient for now)
- Frontend WebSocket client refactoring (backend-focused change)

## Decisions

### Decision 1: Dependency Injection Pattern for WebSocketManager
**What**: Use FastAPI's dependency injection system to provide single WebSocketManager instance to all routes

**Why**:
- Ensures exactly one manager instance exists application-wide
- Makes testing easier (can inject mock managers)
- Follows FastAPI best practices
- Explicit dependencies are more maintainable than global state

**Alternatives Considered**:
- **Global singleton variable**: Current approach, causes multi-instance bugs
- **Module-level initialization**: Hard to test, implicit dependencies
- **Service registry pattern**: Over-engineering for single dependency

**Implementation**:
```python
# app.py
websocket_manager = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global websocket_manager
    from .session_manager import session_manager
    websocket_manager = WebSocketManager(session_manager)
    logger.info("✅ WebSocketManager singleton initialized")
    yield
    # cleanup

def get_websocket_manager() -> WebSocketManager:
    if websocket_manager is None:
        raise RuntimeError("WebSocketManager not initialized")
    return websocket_manager

# routes/session.py
async def send_unified_message(
    manager: WebSocketManager = Depends(get_websocket_manager)
):
    await manager.broadcast_with_differentiated_content(...)
```

### Decision 2: Terminology Standardization - "Customer" over "Client"
**What**: Use "customer" for end-users, reserve "client" for technical contexts only

**Why**:
- Reduces ambiguity (is "client" the person or the HTTP client?)
- Matches business domain language (admin serves customers)
- Aligns with existing `ClientType.customer` enum value
- Improves code readability

**Migration**:
- Keep `client_type` parameter names for API compatibility (document as accepting `admin|customer`)
- Rename internal variables: `client_id` → `customer_id`, `client_message` → `customer_message`
- Update all comments and docstrings
- Add linter rule to prevent future "client" usage in wrong context

**Exceptions**:
- Technical contexts: "WebSocket client", "HTTP client", "client library"
- Existing API field names (breaking change avoided)
- Third-party library references

### Decision 3: Explicit Broadcast Validation
**What**: Validate manager state before broadcasting, return success/failure status

**Why**:
- Silent failures are the root cause of current bug
- Operators need visibility into broadcast health
- Enables alerting on failure rates
- Helps debugging connection issues

**Implementation**:
```python
async def broadcast_with_differentiated_content(...) -> BroadcastResult:
    if session_id not in self.session_connections:
        logger.warning(f"⚠️ No connections for session {session_id}")
        return BroadcastResult(success=False, reason="no_connections")

    connections = self.session_connections[session_id]
    if not connections:
        logger.warning(f"⚠️ Empty connection pool for {session_id}")
        return BroadcastResult(success=False, reason="empty_pool")

    sent_count = 0
    for conn_id, conn in connections.items():
        try:
            await conn.websocket.send_json(message)
            sent_count += 1
        except Exception as e:
            logger.error(f"❌ Broadcast failed to {conn_id}: {e}")

    return BroadcastResult(
        success=sent_count > 0,
        sent_count=sent_count,
        total_connections=len(connections)
    )
```

### Decision 4: Heartbeat Pong in E2E Tests
**What**: Test WebSocket clients must respond to heartbeat pings

**Why**:
- Mimics real frontend behavior
- Prevents premature connection timeouts during tests
- Validates full WebSocket lifecycle
- Exposes heartbeat configuration issues

**Implementation**:
```python
async def handle_websocket_messages(ws):
    async for msg in ws:
        data = json.loads(msg)
        if data.get("type") == "heartbeat_ping":
            await ws.send(json.dumps({
                "type": "heartbeat_pong",
                "timestamp": datetime.now().isoformat()
            }))
        elif data.get("type") == "translation_ready":
            # Handle translation message
```

## Risks / Trade-offs

### Risk 1: Breaking Existing WebSocket Connections on Deployment
**Impact**: Active sessions may drop during deployment

**Mitigation**:
- Use rolling deployment strategy (gradual instance replacement)
- Implement graceful shutdown (send close message before terminating)
- Add reconnection logic with exponential backoff in frontend
- Monitor connection drop rates during deployment window

**Rollback**: Revert to previous container image, existing connections will reconnect

### Risk 2: Performance Impact from Additional Validation
**Impact**: Extra logging and validation may increase latency

**Measurement**:
- Benchmark broadcast latency before/after changes
- Target: <10ms overhead maximum
- Monitor P95/P99 latency in production

**Mitigation**:
- Use async logging (non-blocking)
- Make verbose logging optional via environment variable
- Cache connection pool lookups

### Risk 3: Incomplete Terminology Migration
**Impact**: Mixed naming confuses future developers

**Mitigation**:
- Comprehensive grep audit before merging
- Add linter rules to prevent regression
- Document exceptions explicitly
- Code review checklist includes terminology consistency

## Migration Plan

### Phase 1: Documentation & Analysis (Week 1)
1. Map all WebSocketManager instantiation points
2. Document current architecture with diagrams
3. Create terminology reference
4. Write `websocket-architecture.md` and `api-conventions.md`
5. Get stakeholder review and approval

### Phase 2: Terminology Standardization (Week 2)
1. Create automated script to find/replace terminology
2. Update variable names, comments, docstrings
3. Update documentation files
4. Run full test suite
5. Deploy to staging environment
6. Monitor for issues, collect feedback

### Phase 3: Dependency Injection Implementation (Week 3)
1. Implement DI pattern in `app.py`
2. Update routes to inject manager
3. Remove lazy initialization logic
4. Add startup validation
5. Run integration tests
6. Deploy to staging

### Phase 4: Validation & Error Handling (Week 4)
1. Add broadcast validation logic
2. Implement `BroadcastResult` return type
3. Update error logging throughout
4. Add metrics for broadcast success/failure
5. Update Grafana dashboards
6. Deploy to staging

### Phase 5: E2E Test Hardening (Week 5)
1. Add heartbeat pong handling
2. Increase connection timeout
3. Add health checks
4. Verify 100% message delivery
5. Run load tests
6. Document test patterns

### Phase 6: Production Deployment (Week 6)
1. Feature flag for new logic (gradual rollout)
2. Deploy to 10% of production instances
3. Monitor metrics for 24 hours
4. Increase to 50% if healthy
5. Full rollout after 48 hours of stability
6. Remove feature flag after 1 week

### Rollback Strategy
- **Immediate**: Revert feature flag (0% rollout)
- **Fast**: Deploy previous container image version
- **Safe**: Database/Redis state compatible with both versions
- **Verification**: Run E2E tests against rolled-back version

## Open Questions

1. **Should we add circuit breaker for broadcast failures?**
   - Threshold: 3 consecutive failures
   - Action: Temporarily disable broadcasting, use polling fallback
   - Recovery: Auto-retry after 30 seconds

2. **Do we need message persistence for offline clients?**
   - Current: Messages lost if client disconnected
   - Alternative: Queue messages in Redis for 5 minutes
   - Decision needed: Stakeholder input on offline message delivery requirements

3. **Should we implement broadcast retries?**
   - Current: Single attempt, fail fast
   - Alternative: 3 retries with exponential backoff
   - Trade-off: Latency increase vs. reliability

4. **What's the target for terminology migration completeness?**
   - 100% (strict): May require API version bump
   - 95% (pragmatic): Document exceptions, focus on new code
   - Recommendation: 95% for phase 1, plan v2 API for 100%

5. **How do we handle WebSocket connections during container restarts?**
   - Current: Connections drop, clients must reconnect
   - Desired: Graceful shutdown with advance warning
   - Implementation: Send `system_shutdown` message 10s before termination
