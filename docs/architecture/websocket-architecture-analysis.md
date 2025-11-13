# WebSocket Architecture Analysis

## Date: 2025-11-05

## 1. WebSocketManager Instantiation Points

### 1.1 Primary Instance (websocket.py)
**Location**: `services/api_gateway/websocket.py:1212-1224`

```python
# Global variable declaration
websocket_manager: Optional[WebSocketManager] = None

def get_websocket_manager() -> WebSocketManager:
    """Dependency injection factory"""
    global websocket_manager
    if websocket_manager is None:
        from .session_manager import session_manager
        websocket_manager = WebSocketManager(session_manager)
    return websocket_manager
```

**Usage**: Used in WebSocket endpoints via FastAPI's `Depends()` mechanism
- `/ws/{session_id}/{client_type}` (line 1233)
- Various monitoring and polling endpoints (lines 1305, 1315, 1392, 1414)

**Status**: ✅ Correct pattern - Lazy singleton with dependency injection

### 1.2 Secondary Instance (routes/session.py - Line 572)
**Location**: `services/api_gateway/routes/session.py:569-573`

```python
async def broadcast_message_to_session(...):
    global websocket_manager
    if websocket_manager is None:
        logger.error(f"🔧 WebSocketManager ist None, erstelle neuen...")
        websocket_manager = WebSocketManager(session_manager)  # ❌ PROBLEM!
```

**Problem**: Creates **NEW** WebSocketManager instance if global variable is None
- This instance has empty `session_connections` dictionary
- Broadcasting succeeds but sends to empty manager
- The actual connections are in the manager from `websocket.py`

**Impact**: 🔴 **CRITICAL** - This is the root cause of message delivery failure

### 1.3 Tertiary Instance (routes/session.py - Line 693)
**Location**: `services/api_gateway/routes/session.py:690-693`

```python
async def get_polling_messages(...):
    global websocket_manager
    if websocket_manager is None:
        from ..websocket import WebSocketManager
        websocket_manager = WebSocketManager(session_manager)  # ❌ DUPLICATE
```

**Problem**: Same issue as 1.2 - creates separate instance for polling fallback

**Impact**: 🟡 **MEDIUM** - Polling fallback also fails silently

## 2. Root Cause Analysis

### Why Multiple Instances Exist

1. **Module Isolation**: `routes/session.py` imports `websocket_manager` but it's `None`
   - Reason: The variable in `session.py` is a **different global** than in `websocket.py`
   - Each Python module has its own global namespace

2. **Import Statement**:
   ```python
   # routes/session.py:28
   from ..websocket import MessageType, WebSocketManager
   ```
   - Imports the **class**, not the **instance**
   - The instance `websocket_manager` is never imported

3. **Lazy Initialization Trap**:
   - `websocket.py` initializes when `get_websocket_manager()` is called
   - `session.py` never calls this function, creates own instance instead

### Connection Pool State

**Manager in `websocket.py`** (via `get_websocket_manager()`):
```python
session_connections = {
    "53F795DE": {
        "53F795DE_admin_1762347760": WebSocketConnection(...),
        "53F795DE_customer_1762347760": WebSocketConnection(...)
    }
}
all_connections = {
    "53F795DE_admin_1762347760": WebSocketConnection(...),
    "53F795DE_customer_1762347760": WebSocketConnection(...)
}
```

**Manager in `routes/session.py`** (newly created):
```python
session_connections = {}  # EMPTY!
all_connections = {}      # EMPTY!
```

### Broadcasting Flow (Current - Broken)

```
1. HTTP POST /api/session/{id}/message
   ↓
2. send_unified_message() in session.py
   ↓
3. process_wav() → pipeline processing
   ↓
4. broadcast_message_to_session()
   ↓
5. Check: websocket_manager is None? → YES (different global namespace)
   ↓
6. Create NEW WebSocketManager(session_manager)
   ↓
7. Call new_manager.broadcast_with_differentiated_content(...)
   ↓
8. Check: session_id in session_connections? → NO (empty dict)
   ↓
9. Return early, no error logged
   ↓
10. ❌ Message never delivered to actual WebSocket connections
```

## 3. Singleton Pattern Failure Analysis

### Expected Singleton Behavior
- ✅ One instance per application lifecycle
- ✅ All code uses same instance
- ✅ Shared state (connections) across all access points

### Actual Behavior
- ❌ Minimum 2 instances created per request
- ❌ Different modules use different instances
- ❌ State fragmented across instances

### Why Pattern Failed

**Python Global Scope Misunderstanding**:
```python
# In websocket.py
websocket_manager = None  # Global in websocket module

# In session.py
websocket_manager = None  # DIFFERENT global in session module!
```

These are **completely separate variables** despite having the same name.

### Correct Pattern (To Implement)

**Option A: Shared Module-Level Import**
```python
# session.py
from ..websocket import get_websocket_manager

async def broadcast_message_to_session(...):
    manager = get_websocket_manager()  # Always returns same instance
    await manager.broadcast_with_differentiated_content(...)
```

**Option B: Dependency Injection (Preferred)**
```python
# session.py
from fastapi import Depends
from ..websocket import get_websocket_manager, WebSocketManager

@router.post("/api/session/{session_id}/message")
async def send_unified_message(
    manager: WebSocketManager = Depends(get_websocket_manager)
):
    await broadcast_message_to_session(session_id, message, sender, manager)
```

## 4. Impact Assessment

### Affected Code Paths

1. **Audio Message Broadcasting** (routes/session.py:545)
   - Success rate: 0%
   - Silent failure: Yes
   - Logs: "✅ WebSocket-Broadcasting erfolgreich" (lie)

2. **Text Message Broadcasting** (if implemented)
   - Same failure mode

3. **Polling Fallback** (routes/session.py:693)
   - Cannot retrieve messages (wrong manager)
   - Fallback also fails

### User Impact

- **Admin**: Sends message, sees "sent" confirmation, customer receives nothing
- **Customer**: Sends message, sees "sent" confirmation, admin receives nothing
- **Both**: Must manually refresh to see messages (defeats real-time purpose)

### Log Evidence

```
2025-11-05 13:02:43,783 ERROR 🔧 WebSocketManager ist None, erstelle neuen...
2025-11-05 13:02:43,783 ERROR ✅ WebSocketManager erstellt
2025-11-05 13:02:43,783 ERROR 📤 Sende differentiated broadcast für 53F795DE...
2025-11-05 13:02:43,783 ERROR ✅ Differentiated broadcast abgeschlossen für 53F795DE
2025-11-05 13:03:49,335 WARNING ⚠️ Keine WebSocket-Verbindungen für Session 53F795DE
```

**Translation**: "Created new manager" → broadcasts to empty manager → "success" (but nothing sent)

## 5. Fix Strategy

### Immediate Fix (Minimal Change)
1. Import `get_websocket_manager` in `session.py`
2. Replace lazy init with function call
3. Test E2E delivery

### Proper Fix (Architectural)
1. Remove all global `websocket_manager` variables
2. Use FastAPI dependency injection throughout
3. Initialize singleton in `app.py` lifespan
4. Add validation that manager has connections before broadcasting

### Verification Steps
1. Search codebase for `WebSocketManager(` → should only exist in one place
2. Run E2E test → verify 100% delivery success
3. Check logs → no more "WebSocketManager ist None"
4. Monitor Grafana → broadcast success rate metrics

## Next Steps

1. ✅ Complete this analysis document
2. ⏭️ Create sequence diagrams (current vs. fixed state)
3. ⏭️ Implement dependency injection fix
4. ⏭️ Add broadcast validation
5. ⏭️ Update E2E tests with heartbeat pong
6. ⏭️ Verify 100% message delivery
