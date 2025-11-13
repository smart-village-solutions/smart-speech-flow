# Change: Refactor WebSocket Architecture and Clarify Terminology

## Why

The current WebSocket broadcasting system has critical architectural issues that prevent real-time message delivery:

1. **Multiple WebSocketManager Instances**: The system creates separate WebSocketManager instances in different modules (`websocket.py` and `session.py`), leading to a manager with active connections being unable to broadcast because messages are sent to a different, empty manager instance.

2. **Inconsistent Terminology**: The codebase uses `client` and `customer` interchangeably, causing confusion:
   - API endpoints use `client_type` parameter
   - Enum is named `ClientType` with values `admin` and `customer`
   - WebSocket paths use `/ws/{session_id}/{client_type}`
   - Documentation sometimes refers to "client" when meaning "customer"

3. **Missing Architectural Documentation**: There is no compact, authoritative reference for:
   - WebSocket connection lifecycle and manager responsibilities
   - Message flow from HTTP endpoint → Pipeline → Broadcasting → WebSocket delivery
   - Singleton pattern requirements and dependency injection strategy
   - Field naming conventions and type definitions

4. **Hidden Failures**: Broadcasting completes "successfully" but messages don't arrive because:
   - The wrong manager instance is used (empty one instead of populated one)
   - No error logging when `session_id not in session_connections`
   - Heartbeat timeouts occur without proper client-side pong handling

## What Changes

### Architecture Refactoring
- **BREAKING**: Establish single WebSocketManager instance via dependency injection pattern
- **BREAKING**: Remove lazy initialization of WebSocketManager in `session.py`
- Implement proper FastAPI dependency injection for WebSocketManager access
- Add comprehensive error logging for all broadcast operations
- Document singleton pattern and instance lifecycle

### Terminology Standardization
- **BREAKING**: Rename all occurrences of "client" to "customer" in code and documentation where referring to end-users
- Establish clear naming convention:
  - **Admin**: Administrative staff (German-speaking)
  - **Customer**: End-users/citizens (multilingual)
  - **Client**: Reserved for technical contexts (HTTP client, WebSocket client)
- Update all API parameters, enums, and variable names consistently
- Create terminology reference document

### Documentation Creation
- Create `docs/websocket-architecture.md` with:
  - Component diagram showing manager instances and connections
  - Message flow sequence diagrams
  - Singleton pattern implementation details
  - Error handling and logging strategy
- Create `docs/api-conventions.md` with:
  - Field naming standards
  - Type definitions and enums
  - Request/response schemas
  - Terminology reference

### Error Handling Improvements
- Add explicit validation that WebSocketManager instance has connections before broadcasting
- Log warnings when broadcasting to sessions with no active connections
- Implement connection health checks in E2E tests
- Add heartbeat pong handling in test WebSocket clients

## Impact

### Affected Capabilities
- `websocket-messaging`: Complete refactor of manager instantiation
- `session-management`: Update terminology and dependency injection
- `message-broadcasting`: Fix instance resolution and add validation
- `api-endpoints`: Rename parameters and update documentation

### Affected Code
- `services/api_gateway/websocket.py`: Remove global instance, add DI factory
- `services/api_gateway/routes/session.py`: Remove lazy init, inject manager
- `services/api_gateway/app.py`: Initialize singleton manager at startup
- `test_end_to_end_conversation.py`: Add heartbeat pong handling
- All documentation files: Update terminology consistency

### Breaking Changes
- API parameter `client_type` remains but documentation clarifies it accepts `admin|customer`
- Internal variable names change from `client` to `customer` (code-level breaking)
- WebSocketManager constructor signature may change to support DI

### Migration Path
1. Deploy terminology fixes first (search/replace)
2. Implement DI pattern for WebSocketManager
3. Update all imports and references
4. Add validation and error logging
5. Update tests with heartbeat handling
6. Verify E2E message delivery works

### Risks
- **High**: Existing WebSocket connections may need reconnection after deployment
- **Medium**: Code using old variable names will break until updated
- **Low**: Performance impact from additional validation logging

### Success Metrics
- E2E test completes with 100% message delivery success rate
- No "WebSocketManager ist None" log entries
- All WebSocket messages delivered within 100ms latency
- Zero terminology inconsistencies in codebase (verified by grep)
