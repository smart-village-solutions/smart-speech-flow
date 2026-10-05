## ADDED Requirements

### Requirement: Non-blocking tenant persistence

The gateway SHALL reach the tenant session store and the realtime ticket store through asynchronous ports backed by an asynchronous Redis client, so that no request, WebSocket or background handler blocks the event loop on a Redis round trip. Writes to one session SHALL apply in the order they were issued.

#### Scenario: Request during a slow Redis round trip

- **WHEN** one handler is awaiting a session read or write from Redis
- **THEN** the event loop continues to serve other requests, sockets and heartbeats

#### Scenario: Concurrent writes to one session

- **WHEN** two handlers change the same session and both save it
- **THEN** the store ends holding the session's latest state, never an older snapshot

#### Scenario: Change racing a termination

- **WHEN** a connection, activation or message for a session waits for its write while that session is terminated
- **THEN** the change fails as it would on an already terminated session, and no participant joins or is told of success after the termination

#### Scenario: Synchronous client reintroduced

- **WHEN** a production gateway module imports the synchronous Redis client, other than the offline cutover CLI and the legacy session manager that no production path constructs
- **THEN** the hermetic test suite fails and names the module
