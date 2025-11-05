# ADR 001: WebSocketManager Singleton Pattern

**Status:** Accepted
**Date:** 2025-11-05
**Decision Makers:** Backend Team
**Stakeholders:** Frontend Team, DevOps

## Context

Das Smart Speech Flow Backend benötigt eine zentrale Verwaltung von WebSocket-Verbindungen für Echtzeit-Kommunikation zwischen Admin und Customer. Jede Session kann maximal zwei aktive WebSocket-Verbindungen haben (eine für Admin, eine für Customer), über die bidirektional Nachrichten übersetzt und zugestellt werden.

### Problem Statement

**Ursprüngliche Architektur:**
- Mehrere WebSocketManager-Instanzen wurden in verschiedenen Routen erzeugt
- Lazy Initialization führte zu Race Conditions
- Globale Variablen in `routes/session.py` ermöglichten None-Zugriffe
- Broadcasting war inkonsistent (manche Nachrichten kamen nicht an)

**Symptome:**
- 0% Message Delivery Rate in E2E Tests
- `NameError: name 'manager' is not defined` in Logs
- Inkonsistente Session-Verbindungen über verschiedene Endpunkte
- Keine zentrale Übersicht über alle aktiven Verbindungen

## Decision

Wir implementieren ein **Singleton Pattern** für den WebSocketManager mit **FastAPI Dependency Injection**.

### Architektur

```python
# services/api_gateway/websocket.py
_websocket_manager: Optional[WebSocketManager] = None

def get_websocket_manager() -> WebSocketManager:
    """Singleton Getter für WebSocketManager (FastAPI Dependency)"""
    global _websocket_manager
    if _websocket_manager is None:
        raise RuntimeError("WebSocketManager not initialized")
    return _websocket_manager

# services/api_gateway/app.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Eine einzige Manager-Instanz erstellen
    global _websocket_manager
    _websocket_manager = WebSocketManager()
    yield
    # Shutdown: Cleanup

# routes/session.py
async def send_unified_message(
    manager: WebSocketManager = Depends(get_websocket_manager)
):
    # Manager wird automatisch injiziert
    await manager.broadcast_with_differentiated_content(...)
```

### Key Design Principles

1. **Single Source of Truth:** Genau eine WebSocketManager-Instanz pro Applikation
2. **Dependency Injection:** FastAPI Depends() garantiert korrekte Initialisierung
3. **Fail-Fast:** RuntimeError wenn Manager nicht initialisiert (verhindert Silent Failures)
4. **Centralized State:** Alle Session-Verbindungen in einer `session_connections` Dict

## Consequences

### Positive

✅ **100% Message Delivery Rate** - E2E Tests zeigen vollständige Zustellung
✅ **Keine Race Conditions** - Eine Instanz eliminiert Threading-Probleme
✅ **Konsistente Session-Verwaltung** - Alle Routes sehen dieselben Verbindungen
✅ **Prometheus Metrics** - Zentrale Erfassung aller Broadcasts
✅ **Testbarkeit** - Singleton kann in Tests durch Mock ersetzt werden
✅ **Klare Ownership** - Lifecycle Management im Application Lifespan

### Negative

⚠️ **Global State** - Singleton ist technisch globaler State (aber kontrolliert)
⚠️ **Restart erforderlich** - Bei Code-Änderungen muss Container neu gebaut werden
⚠️ **Docker Compose Bug** - Container-Recreate schlägt manchmal fehl (Workaround dokumentiert)

### Neutral

🔹 **Memory Footprint** - Eine Instanz spart Memory vs. multiple Manager
🔹 **Scalability** - Horizontale Skalierung benötigt Redis-Backed Session Store (zukünftig)

## Alternatives Considered

### Alternative 1: Manager Instance per Route
```python
# Jede Route erstellt eigenen Manager
manager = WebSocketManager()
await manager.connect_websocket(...)
```

**Rejected because:**
- ❌ Verbindungen sind isoliert zwischen Routes
- ❌ Session-State ist fragmentiert
- ❌ Broadcasting erreicht nicht alle Clients

### Alternative 2: Class-Level Singleton
```python
class WebSocketManager:
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
```

**Rejected because:**
- ❌ Schwerer zu testen (Singleton bleibt zwischen Tests)
- ❌ Keine Lifecycle-Integration mit FastAPI
- ❌ Implizite Initialization (schwer zu debuggen)

### Alternative 3: Redis-Backed Distributed Manager
```python
# Verbindungen in Redis speichern für Multi-Container Setup
redis_store = RedisSessionStore()
manager = DistributedWebSocketManager(redis_store)
```

**Deferred because:**
- ⏳ Überengineering für aktuelles Deployment (Single Container)
- ⏳ Erhöht Latenz (Redis Round-Trip für jede Broadcast)
- ⏳ Kann später implementiert werden wenn horizontal skaliert wird

## Implementation Notes

### Migration Path (Phase 6-7)

1. ✅ Globale `websocket_manager` Variablen entfernt
2. ✅ `get_websocket_manager()` Dependency in alle Routes injiziert
3. ✅ `broadcast_with_differentiated_content` gibt BroadcastResult zurück
4. ✅ Prometheus Metrics für Success/Failure Rate
5. ✅ E2E Tests validieren 100% Delivery

### Breaking Changes

**NONE** - API bleibt unverändert, nur interne Architektur

### Rollback Plan

Falls kritische Probleme auftreten:
```bash
git revert <commit-hash>
docker-compose up -d --force-recreate api_gateway
```

Alle Tests müssen nach Rollback grün sein (bestätigt durch CI/CD).

## Monitoring & Validation

### Metrics (Prometheus)

```promql
# Erfolgsquote berechnen
rate(websocket_broadcast_success_total[5m]) /
rate(websocket_broadcast_total[5m]) * 100

# Fehlerrate überwachen
rate(websocket_broadcast_failure_total[5m])

# Message Delivery Count
sum(websocket_broadcast_messages_delivered_total)
```

**Baseline nach Implementation:**
- Success Rate: **100%**
- Failure Rate: **0%**
- Messages Delivered: **4/4** in E2E Test

### Tests

```bash
# Unit Tests
pytest services/api_gateway/tests/test_websocket_manager.py::test_websocket_manager_singleton_behavior

# E2E Test
python3 test_end_to_end_conversation.py

# Load Test
python3 test_concurrent_sessions.py
```

**Expected Results:**
- Singleton Test: ✅ Same instance ID across all calls
- E2E Test: ✅ 100% message delivery rate
- Load Test: ✅ 5 concurrent sessions, 3 messages each

## Related Documents

- [WebSocket Architecture Analysis](../websocket-architecture-analysis.md)
- [API Conventions](../api-conventions.md)
- [Session Flow](../session_flow.md)
- [Tasks: Phase 3 - WebSocketManager Singleton Implementation](../../openspec/changes/refactor-websocket-architecture/tasks.md#3-websocketmanager-singleton-implementation)

## Future Considerations

### Horizontal Scaling (Multi-Container)

Wenn das System horizontal skaliert wird, benötigt der WebSocketManager:

1. **Redis-Backed Session Store**
   - Shared state über Container hinweg
   - Pub/Sub für Broadcasts zwischen Containern

2. **Sticky Sessions**
   - Load Balancer muss WebSocket-Verbindungen zum selben Container routen
   - Session Affinity basierend auf Session ID

3. **Health Checks**
   - `/health` Endpoint muss WebSocketManager-Status prüfen
   - Readiness Probe für Kubernetes/Docker Swarm

### WebSocket Clustering

```python
# Konzept für zukünftige Implementation
class DistributedWebSocketManager:
    def __init__(self, redis_client: Redis):
        self.redis = redis_client
        self.local_connections = {}

    async def broadcast_to_cluster(self, session_id: str, message: dict):
        # Publish to Redis Pub/Sub
        await self.redis.publish(f"session:{session_id}", json.dumps(message))

        # Subscribe to Redis for messages from other containers
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(f"session:{session_id}")
```

**Timeline:** Q1 2026 (wenn Load >100 concurrent sessions)

---

**Approval:** ✅ Approved by Backend Team (2025-11-05)
**Review Date:** 2026-03-01 (nach 3 Monaten Production Experience)
