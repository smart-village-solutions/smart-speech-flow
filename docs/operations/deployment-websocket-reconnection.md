# Deployment Guide: WebSocket Reconnection Strategy

**Audience:** DevOps, Frontend Developers
**Version:** 1.1.0
**Last Updated:** 2025-11-05

## Overview

Dieses Dokument beschreibt, wie WebSocket-Verbindungen bei Container-Restarts erhalten bleiben und wie das Frontend automatisch reconnectet.

## Problem Statement

**Scenario:** API Gateway Container wird neu gestartet (Code-Update, Deployment, Crash)

**Impact:**
- Alle WebSocket-Verbindungen werden geschlossen
- In-Memory Session-State geht verloren (session_connections)
- Admin und Customer müssen manuell neu verbinden

**Goal:** Automatisches Reconnect mit minimaler User-Disruption

## Architecture

### Backend: Stateless WebSocket Manager

```python
# WebSocketManager speichert Verbindungen in-memory
self.session_connections: Dict[str, Dict[str, List[WebSocket]]] = {}

# Bei Container-Restart geht dieser State verloren!
```

**Design Decision:** Keine persistente WebSocket-State-Speicherung

**Rationale:**
- WebSocket-Verbindungen sind per Definition ephemeral (TCP-basiert)
- Redis kann keine Live-WebSocket-Objekte speichern
- Reconnection ist ein Standard-Pattern für alle WebSocket-Apps

### Frontend: Automatic Reconnection

Das Frontend muss automatisches Reconnect implementieren:

```javascript
class WebSocketClient {
  constructor(sessionId, connectionType) {
    this.sessionId = sessionId;
    this.connectionType = connectionType; // "admin" or "customer"
    this.ws = null;
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 10;
    this.reconnectDelay = 1000; // Start with 1s
    this.isIntentionallyClosed = false;
  }

  connect() {
    const wsUrl = `wss://ssf.smart-village.solutions/ws/${this.sessionId}/${this.connectionType}`;

    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      console.log("✅ WebSocket verbunden");
      this.reconnectAttempts = 0; // Reset on success
      this.reconnectDelay = 1000;
    };

    this.ws.onclose = (event) => {
      if (this.isIntentionallyClosed) {
        console.log("👋 WebSocket bewusst geschlossen");
        return;
      }

      console.warn(`⚠️ WebSocket geschlossen (Code: ${event.code})`);
      this.attemptReconnect();
    };

    this.ws.onerror = (error) => {
      console.error("❌ WebSocket Fehler:", error);
    };

    this.ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      this.handleMessage(message);
    };
  }

  attemptReconnect() {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error("❌ Max reconnect attempts erreicht. Bitte Seite neu laden.");
      // Show user notification
      return;
    }

    this.reconnectAttempts++;

    // Exponential backoff: 1s, 2s, 4s, 8s, max 30s
    this.reconnectDelay = Math.min(
      this.reconnectDelay * 2,
      30000
    );

    console.log(
      `🔄 Reconnect-Versuch ${this.reconnectAttempts}/${this.maxReconnectAttempts} in ${this.reconnectDelay}ms`
    );

    setTimeout(() => {
      this.connect();
    }, this.reconnectDelay);
  }

  handleMessage(message) {
    switch (message.type) {
      case "connection_ack":
        console.log("✅ Verbindung bestätigt:", message.connection_id);
        break;

      case "heartbeat":
        // Respond with pong
        this.ws.send(JSON.stringify({ type: "pong" }));
        break;

      case "message":
        // Display translated message
        this.displayMessage(message);
        break;

      case "session_terminated":
        console.log("🛑 Session beendet");
        this.isIntentionallyClosed = true;
        this.ws.close();
        break;
    }
  }

  close() {
    this.isIntentionallyClosed = true;
    if (this.ws) {
      this.ws.close();
    }
  }
}
```

### Usage Example

```javascript
// Admin Frontend
const wsClient = new WebSocketClient(sessionId, "admin");
wsClient.connect();

// Customer Frontend
const wsClient = new WebSocketClient(sessionId, "customer");
wsClient.connect();

// Cleanup on component unmount
onUnmount(() => {
  wsClient.close();
});
```

## Deployment Procedures

### 1. Zero-Downtime Deployment (Blue-Green)

**Nicht möglich** für WebSocket-Services (keine Sticky Sessions)

**Alternative:** Rolling Update mit kurzer Downtime

```bash
# Step 1: Notify users via broadcast
curl -X POST http://localhost:8000/api/admin/broadcast \
  -H "Content-Type: application/json" \
  -d '{"message": "⚠️ Wartung in 60 Sekunden. Verbindung wird kurz unterbrochen."}'

# Step 2: Wait 60s for users to see notification
sleep 60

# Step 3: Recreate container
docker-compose up -d --no-deps --force-recreate api_gateway

# Step 4: Verify container is running
docker ps | grep api_gateway

# Step 5: Check logs for WebSocketManager initialization
docker logs ssf-backend_api_gateway_1 --tail 50
```

**Expected Output:**
```
🚀 WebSocketManager initialisiert (ID: 128884465899536)
🔌 WebSocket-Monitor gestartet
✅ API Gateway bereit
```

**User Experience:**
- WebSocket schließt (~5s downtime)
- Frontend reconnectet automatisch (1-2s delay)
- Nachrichten in Queue werden nach Reconnect zugestellt

### 2. Emergency Restart (Container Crash)

```bash
# Check if container is running
docker ps -a | grep api_gateway

# If status is "Exited" or "Restarting"
docker logs ssf-backend_api_gateway_1 --tail 100

# Force restart
docker-compose restart api_gateway

# Alternative: Full recreate if restart fails
docker-compose up -d --force-recreate api_gateway
```

### 3. Code Update Deployment

```bash
# 1. Pull latest code
git pull origin main

# 2. Rebuild image
docker-compose build api_gateway

# 3. Recreate container
docker-compose up -d --force-recreate api_gateway

# 4. Verify health
curl http://localhost:8000/health
```

**Troubleshooting Docker Compose Bug:**

Falls `docker-compose up` mit `KeyError: 'ContainerConfig'` fehlschlägt:

```bash
# Workaround: Manual container management
docker stop ssf-backend_api_gateway_1
docker rm ssf-backend_api_gateway_1

# Recreate without dependencies
docker-compose up -d --no-deps api_gateway

# Manually start dependencies if needed
docker start ssf-backend_redis_1
docker start ssf-backend_ollama_1
```

## Session Persistence

### Redis Session Store

Sessions werden in Redis gespeichert und überleben Container-Restarts:

```python
# session_manager.py
async def create_session(self) -> str:
    session_id = generate_short_id()
    session_data = {
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        ...
    }
    # Persist to Redis
    await self.redis_store.set_session(session_id, session_data)
    return session_id
```

**What persists:**
- ✅ Session Metadata (status, languages, timestamps)
- ✅ Message History (original + translated text)
- ✅ Session Configuration

**What does NOT persist:**
- ❌ Active WebSocket connections (ephemeral)
- ❌ In-flight messages (not yet acknowledged)
- ❌ Heartbeat state

### Message Queue for Offline Delivery

**Problem:** Nachricht wird während Reconnect gesendet

**Solution:** Frontend Message Queue

```javascript
class MessageQueue {
  constructor(wsClient) {
    this.wsClient = wsClient;
    this.queue = [];
  }

  sendMessage(message) {
    if (this.wsClient.ws.readyState === WebSocket.OPEN) {
      this.wsClient.ws.send(JSON.stringify(message));
    } else {
      console.log("📬 Nachricht in Queue (WebSocket nicht verbunden)");
      this.queue.push(message);
    }
  }

  flushQueue() {
    while (this.queue.length > 0) {
      const message = this.queue.shift();
      this.wsClient.ws.send(JSON.stringify(message));
    }
  }

  onReconnect() {
    console.log(`📤 ${this.queue.length} Nachrichten aus Queue senden`);
    this.flushQueue();
  }
}
```

## Monitoring & Alerts

### Prometheus Metrics

```promql
# WebSocket Connection Count
websocket_connections_total{session_id="ABC12345"}

# Reconnection Rate
rate(websocket_reconnections_total[5m])

# Message Queue Size
websocket_message_queue_size
```

### Grafana Alerts

```yaml
# monitoring/alert_rules.yml
- alert: HighWebSocketReconnectionRate
  expr: rate(websocket_reconnections_total[5m]) > 0.5
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Viele WebSocket Reconnects"
    description: "{{ $value }} Reconnects/Sekunde in den letzten 5 Minuten"

- alert: WebSocketMessageQueueBacklog
  expr: websocket_message_queue_size > 100
  for: 2m
  labels:
    severity: critical
  annotations:
    summary: "WebSocket Message Queue Rückstau"
    description: "{{ $value }} Nachrichten in Queue. Container Restart nötig?"
```

### Health Checks

```bash
# Kubernetes Readiness Probe
http:
  path: /health
  port: 8000

# Liveness Probe
http:
  path: /health
  port: 8000
  initialDelaySeconds: 30
  periodSeconds: 10
```

## Best Practices

### Frontend

✅ **DO:**
- Implement exponential backoff for reconnects
- Show user notification during reconnect
- Queue messages during offline period
- Handle session_terminated event gracefully
- Test reconnection with network throttling

❌ **DON'T:**
- Infinite reconnect loop without max attempts
- Silently fail without user feedback
- Lose messages during reconnect
- Hardcode reconnect delays

### Backend

✅ **DO:**
- Log all WebSocket connections/disconnections
- Implement graceful shutdown (close all connections)
- Use Prometheus metrics for monitoring
- Document restart procedures

❌ **DON'T:**
- Store critical state only in-memory
- Skip health checks
- Deploy without testing reconnection
- Restart during peak hours without notification

## Testing Reconnection

### Manual Test

```bash
# 1. Start session and connect WebSocket
# (Open browser DevTools → Network → WS)

# 2. Restart container
docker-compose restart api_gateway

# 3. Verify reconnection in browser console
# Expected: "🔄 Reconnect-Versuch 1/10 in 1000ms"
# Expected: "✅ WebSocket verbunden"
```

### Automated Test

```python
# test_websocket_reconnection.py
import asyncio
import websockets

async def test_reconnection():
    uri = "ws://localhost:8000/ws/ABC12345/admin"

    # Connect
    async with websockets.connect(uri) as ws:
        ack = await ws.recv()
        assert json.loads(ack)["type"] == "connection_ack"

        # Simulate container restart (close connection)
        await ws.close()

    # Wait for backoff delay
    await asyncio.sleep(2)

    # Reconnect
    async with websockets.connect(uri) as ws:
        ack = await ws.recv()
        assert json.loads(ack)["type"] == "connection_ack"
        print("✅ Reconnection successful")

asyncio.run(test_reconnection())
```

## Rollback Plan

Falls Deployment fehlschlägt:

```bash
# 1. Check current image
docker images | grep api_gateway

# 2. Rollback to previous version
docker tag ssf-backend_api_gateway:previous ssf-backend_api_gateway:latest

# 3. Recreate container
docker-compose up -d --force-recreate api_gateway

# 4. Verify
curl http://localhost:8000/health
docker logs ssf-backend_api_gateway_1 --tail 50
```

## Related Documents

- [ADR 001: WebSocket Singleton Pattern](./adr/001-websocket-singleton-pattern.md)
- [Session Flow](./session_flow.md)
- [WebSocket Architecture Analysis](./websocket-architecture-analysis.md)

---

**Approved by:** DevOps Team
**Review Date:** 2026-02-05
