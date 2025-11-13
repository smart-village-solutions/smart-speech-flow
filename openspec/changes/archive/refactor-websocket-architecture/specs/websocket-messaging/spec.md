## ADDED Requirements

### Requirement: WebSocketManager Singleton Pattern
The system SHALL maintain exactly one WebSocketManager instance throughout the application lifecycle.

#### Scenario: Single instance initialization
- **GIVEN** the FastAPI application starts up
- **WHEN** the lifespan context manager executes
- **THEN** exactly one WebSocketManager instance is created and registered globally

#### Scenario: Dependency injection access
- **GIVEN** a route handler needs WebSocketManager access
- **WHEN** the handler declares WebSocketManager as a dependency
- **THEN** the singleton instance is injected without creating a new instance

#### Scenario: Multiple concurrent requests
- **GIVEN** multiple concurrent HTTP requests to message endpoints
- **WHEN** all handlers access WebSocketManager via dependency injection
- **THEN** all handlers receive the same WebSocketManager instance with identical connection pools

### Requirement: Broadcast Validation and Error Reporting
The system SHALL validate WebSocketManager state before broadcasting and return explicit success/failure status.

#### Scenario: Broadcasting to session with active connections
- **GIVEN** a session has 2 active WebSocket connections (admin and customer)
- **WHEN** broadcasting a message to that session
- **THEN** the broadcast SHALL succeed and return `BroadcastResult(success=True, sent_count=2, total_connections=2)`

#### Scenario: Broadcasting to session with no connections
- **GIVEN** a session exists but has no active WebSocket connections
- **WHEN** broadcasting a message to that session
- **THEN** the broadcast SHALL fail and return `BroadcastResult(success=False, reason="no_connections")`
- **AND** a warning SHALL be logged with session ID and connection count

#### Scenario: Broadcasting to non-existent session
- **GIVEN** a session ID that does not exist in the connection pool
- **WHEN** broadcasting a message to that session
- **THEN** the broadcast SHALL fail and return `BroadcastResult(success=False, reason="session_not_found")`
- **AND** an error SHALL be logged with the invalid session ID

#### Scenario: Partial broadcast failure
- **GIVEN** a session with 2 connections where 1 connection is broken
- **WHEN** broadcasting a message to that session
- **THEN** the broadcast SHALL partially succeed with `BroadcastResult(success=True, sent_count=1, total_connections=2)`
- **AND** an error SHALL be logged for the failed connection
- **AND** the failed connection SHALL be removed from the pool

### Requirement: Heartbeat Lifecycle Management
WebSocket connections SHALL implement heartbeat ping/pong mechanism to detect and cleanup dead connections.

#### Scenario: Successful heartbeat exchange
- **GIVEN** an active WebSocket connection
- **WHEN** the server sends a heartbeat_ping message
- **THEN** the client SHALL respond with heartbeat_pong within 5 seconds
- **AND** the connection last_heartbeat timestamp SHALL be updated

#### Scenario: Heartbeat timeout cleanup
- **GIVEN** a WebSocket connection with no heartbeat_pong for 60 seconds
- **WHEN** the heartbeat timeout monitor executes
- **THEN** the connection SHALL be closed with code 1001 (going away)
- **AND** the connection SHALL be removed from all connection pools
- **AND** a warning SHALL be logged with connection ID and timeout duration

#### Scenario: Heartbeat respects connection state
- **GIVEN** multiple WebSocket connections in different states (connected, disconnecting, closed)
- **WHEN** heartbeat pings are sent
- **THEN** only connections in CONNECTED state SHALL receive pings
- **AND** connections in other states SHALL be skipped without error

## MODIFIED Requirements

### Requirement: WebSocket Message Broadcasting
The system SHALL broadcast messages to all connections in a session except the sender, with differentiated content based on recipient role.

**Modified**: Added explicit return type and validation

#### Scenario: Successful differentiated broadcast
- **GIVEN** a session with admin and customer connections
- **WHEN** admin sends a message
- **THEN** customer SHALL receive translated_text and audio_url
- **AND** admin SHALL receive original_text as confirmation
- **AND** the broadcast SHALL return `BroadcastResult(success=True, sent_count=2)`

#### Scenario: Broadcast with logging
- **GIVEN** any broadcast operation
- **WHEN** the broadcast executes
- **THEN** the connection count SHALL be logged before sending
- **AND** each successful send SHALL be logged at INFO level
- **AND** each failed send SHALL be logged at ERROR level with exception details

### Requirement: WebSocket Connection Management
The system SHALL track all WebSocket connections in both session-specific and global connection pools.

**Modified**: Clarified single manager instance requirement

#### Scenario: Connection registration in singleton manager
- **GIVEN** a WebSocket client connects to `/ws/{session_id}/{client_type}`
- **WHEN** the connection is established
- **THEN** the connection SHALL be added to the singleton WebSocketManager's session_connections pool
- **AND** the connection SHALL be added to the singleton WebSocketManager's all_connections pool
- **AND** exactly one manager instance SHALL contain this connection

#### Scenario: Connection cleanup removes from all pools
- **GIVEN** an established WebSocket connection in both pools
- **WHEN** the connection is closed or times out
- **THEN** the connection SHALL be removed from session_connections
- **AND** the connection SHALL be removed from all_connections
- **AND** the cleanup SHALL occur in the same manager instance that registered it

## REMOVED Requirements

None. All existing requirements remain valid with modifications above.
