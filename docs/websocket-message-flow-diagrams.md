# WebSocket Message Flow - Sequence Diagrams

## 1. Current State (Broken) - Message Flow

```mermaid
sequenceDiagram
    participant Client as WebSocket Client<br/>(Admin/Customer)
    participant WS as WebSocket Endpoint<br/>(websocket.py)
    participant WSM1 as WebSocketManager #1<br/>(websocket.py instance)
    participant HTTP as HTTP Endpoint<br/>(session.py)
    participant WSM2 as WebSocketManager #2<br/>(session.py instance)
    participant Pipeline as Audio Pipeline<br/>(ASR→Translation→TTS)

    %% Connection Phase
    Note over Client,WSM1: Connection Phase
    Client->>WS: WebSocket Connect<br/>/ws/{session}/{type}
    WS->>WSM1: get_websocket_manager()
    Note right of WSM1: Lazy init creates<br/>manager instance
    WSM1-->>WS: Returns manager #1
    WS->>WSM1: connect_websocket(...)
    WSM1->>WSM1: Add to session_connections
    WSM1->>WSM1: Add to all_connections
    WSM1-->>Client: connection_ack

    %% Message Sending Phase
    Note over Client,Pipeline: Message Sending Phase
    Client->>HTTP: POST /api/session/{id}/message<br/>(audio file)
    HTTP->>Pipeline: process_wav(audio)
    Pipeline-->>HTTP: {original_text, translated_text, audio}

    %% Broadcasting Phase (BROKEN)
    Note over HTTP,WSM2: Broadcasting Phase - BROKEN
    HTTP->>HTTP: broadcast_message_to_session()
    HTTP->>HTTP: Check: websocket_manager?
    Note right of HTTP: Global var is None!<br/>(Different namespace)
    HTTP->>WSM2: WebSocketManager(session_manager)
    Note right of WSM2: NEW instance created<br/>with empty connections!
    HTTP->>WSM2: broadcast_with_differentiated_content()
    WSM2->>WSM2: Check: session_id in connections?
    Note right of WSM2: session_connections = {}<br/>EMPTY!
    WSM2-->>HTTP: Silent return (early exit)
    HTTP-->>Client: HTTP 200 OK<br/>{status: success}

    %% No WebSocket Delivery
    Note over Client,WSM1: ❌ Message Never Delivered
    Note right of WSM1: Manager #1 has connections<br/>but never called
    Note right of WSM2: Manager #2 was called<br/>but has no connections
```

## 2. Expected State (After Fix) - Message Flow

```mermaid
sequenceDiagram
    participant Client as WebSocket Client<br/>(Admin/Customer)
    participant WS as WebSocket Endpoint<br/>(websocket.py)
    participant WSM as WebSocketManager<br/>(Singleton Instance)
    participant HTTP as HTTP Endpoint<br/>(session.py)
    participant Pipeline as Audio Pipeline<br/>(ASR→Translation→TTS)

    %% Connection Phase
    Note over Client,WSM: Connection Phase
    Client->>WS: WebSocket Connect<br/>/ws/{session}/{type}
    WS->>WSM: get_websocket_manager()
    Note right of WSM: Returns singleton<br/>instance
    WSM-->>WS: Returns manager
    WS->>WSM: connect_websocket(...)
    WSM->>WSM: Add to session_connections
    WSM->>WSM: Add to all_connections
    WSM-->>Client: connection_ack

    %% Message Sending Phase
    Note over Client,Pipeline: Message Sending Phase
    Client->>HTTP: POST /api/session/{id}/message<br/>(audio file)
    HTTP->>HTTP: Inject manager via Depends()
    HTTP->>Pipeline: process_wav(audio)
    Pipeline-->>HTTP: {original_text, translated_text, audio}

    %% Broadcasting Phase (WORKING)
    Note over HTTP,WSM: Broadcasting Phase - WORKING ✅
    HTTP->>HTTP: broadcast_message_to_session(manager)
    HTTP->>WSM: broadcast_with_differentiated_content()
    WSM->>WSM: Check: session_id in connections?
    Note right of WSM: Connections exist!
    WSM->>WSM: Validate connections alive

    loop For each connection in session
        WSM->>Client: WebSocket.send_json(message)
        Note right of Client: Differentiated content:<br/>- Sender: original_text<br/>- Receiver: translated_text + audio
    end

    WSM-->>HTTP: BroadcastResult(success=True, sent=2)
    HTTP-->>Client: HTTP 200 OK<br/>{status: success}

    %% Successful Delivery
    Note over Client,WSM: ✅ Messages Delivered in Real-Time (<100ms)
```

## 3. Dependency Injection Flow (Target Architecture)

```mermaid
sequenceDiagram
    participant App as FastAPI App<br/>(app.py)
    participant Lifespan as Lifespan Context
    participant SM as SessionManager
    participant WSM as WebSocketManager<br/>(Singleton)
    participant Routes as Route Handlers

    %% Startup Phase
    Note over App,WSM: Application Startup
    App->>Lifespan: lifespan(app)
    Lifespan->>SM: Initialize SessionManager
    SM-->>Lifespan: session_manager instance
    Lifespan->>WSM: WebSocketManager(session_manager)
    Note right of WSM: Single instance created<br/>at startup
    WSM->>SM: register_websocket_manager(self)
    WSM-->>Lifespan: websocket_manager instance
    Lifespan->>App: Set global websocket_manager
    Note right of App: App ready with<br/>singleton manager

    %% Request Phase
    Note over App,Routes: Incoming Request
    Routes->>Routes: Depends(get_websocket_manager)
    Routes->>App: get_websocket_manager()
    App-->>Routes: Returns singleton instance
    Note right of Routes: Always same instance<br/>with all connections

    %% Shutdown Phase
    Note over App,WSM: Application Shutdown
    App->>Lifespan: Cleanup
    Lifespan->>WSM: Close all connections
    WSM->>WSM: Disconnect all clients gracefully
    Lifespan->>WSM: Destroy instance
```

## 4. Broadcasting Validation Flow (New)

```mermaid
sequenceDiagram
    participant Route as Route Handler
    participant Broadcast as broadcast_message_to_session()
    participant WSM as WebSocketManager
    participant Conn as WebSocket Connection
    participant Metrics as Prometheus Metrics

    Route->>Broadcast: broadcast_message_to_session(manager, ...)

    %% Validation Phase
    Broadcast->>WSM: Check session_connections
    alt Session not found
        WSM-->>Broadcast: session_id not in connections
        Broadcast->>Broadcast: Log WARNING
        Broadcast->>Metrics: Increment broadcast_failures
        Broadcast-->>Route: BroadcastResult(success=False, reason="no_connections")
    else Session found but empty
        WSM-->>Broadcast: connections = {}
        Broadcast->>Broadcast: Log WARNING
        Broadcast->>Metrics: Increment broadcast_failures
        Broadcast-->>Route: BroadcastResult(success=False, reason="empty_pool")
    else Connections exist
        WSM-->>Broadcast: connections = {admin: ..., customer: ...}
        Broadcast->>Broadcast: Log INFO (connection count)

        %% Broadcasting Phase
        loop For each connection
            Broadcast->>Conn: Check is_alive()
            alt Connection alive
                Broadcast->>Conn: websocket.send_json(message)
                Conn-->>Broadcast: Success
                Broadcast->>Broadcast: Increment sent_count
            else Connection dead
                Broadcast->>Broadcast: Log ERROR
                Broadcast->>WSM: Remove dead connection
                Broadcast->>Broadcast: Increment failed_count
            end
        end

        %% Result Phase
        Broadcast->>Metrics: Increment broadcast_success
        Broadcast->>Broadcast: Log SUCCESS (sent/total)
        Broadcast-->>Route: BroadcastResult(success=True, sent=2, total=2)
    end
```

## 5. Heartbeat Management Flow

```mermaid
sequenceDiagram
    participant WSM as WebSocketManager<br/>(Background Task)
    participant Conn as WebSocket Connection
    participant Client as WebSocket Client

    %% Heartbeat Loop
    loop Every 30 seconds
        WSM->>WSM: _send_heartbeat_pings()

        loop For each connection
            WSM->>Conn: Check state == CONNECTED
            alt Connected
                WSM->>Client: send_json({type: "heartbeat_ping"})

                alt Client responds
                    Client->>WSM: {type: "heartbeat_pong"}
                    WSM->>Conn: Update last_heartbeat timestamp
                    WSM->>Conn: Set state = CONNECTED
                else Client timeout (60s)
                    Note over WSM,Client: No pong received
                    WSM->>WSM: _check_heartbeat_timeouts()
                    WSM->>Conn: Check last_heartbeat < 60s ago?
                    WSM->>Client: close(code=1001, reason="heartbeat_timeout")
                    WSM->>WSM: Remove from all pools
                    WSM->>WSM: Log WARNING + Increment metric
                end
            end
        end
    end
```

## Key Differences: Current vs. Target

| Aspect | Current (Broken) | Target (Fixed) |
|--------|-----------------|----------------|
| **Manager Instances** | 2+ instances per request | 1 singleton instance |
| **Instance Creation** | Lazy init on first access | Created at app startup |
| **Dependency Injection** | Manual global variable | FastAPI `Depends()` |
| **Connection Pools** | Fragmented across instances | Shared in single instance |
| **Broadcasting** | Silent failure (empty pool) | Validated with error logging |
| **Return Type** | `None` (void) | `BroadcastResult` with status |
| **Error Visibility** | "Success" logs for failures | Explicit failure reporting |
| **Metrics** | No broadcast metrics | Success/failure counters |
| **Message Delivery** | 0% success rate | 100% success rate (goal) |

## Implementation Priority

1. **Critical**: Fix singleton pattern (prevent multiple instances)
2. **High**: Add broadcast validation and error reporting
3. **Medium**: Implement proper dependency injection
4. **Low**: Add metrics and monitoring

## Testing Verification Points

- [ ] Only one `WebSocketManager` instance exists at runtime
- [ ] All routes receive same instance via DI
- [ ] Broadcasting logs connection count before sending
- [ ] Failed broadcasts return `BroadcastResult(success=False)`
- [ ] E2E test shows 100% message delivery
- [ ] No "WebSocketManager ist None" in logs
- [ ] Metrics show broadcast success rate
