# Runbook: WebSocket Broadcast Failures

**Alert:** `WebSocketBroadcastFailureRateHigh`
**Severity:** Critical
**Threshold:** Broadcast failure rate > 1% for 2 minutes
**Owner:** Backend Team
**Last Updated:** 2025-11-05

## Alert Description

This alert fires when the WebSocket broadcast failure rate exceeds 1%, indicating that messages are not being delivered to connected clients despite the broadcasting system attempting to send them.

## Impact

**User Experience:**
- Admin does NOT receive translated messages from Customer
- Customer does NOT receive translated messages from Admin
- Real-time communication is broken
- Users may see "Connection established" but messages don't arrive

**Business Impact:**
- Live translation sessions are non-functional
- Customer service is degraded
- Users must manually refresh or reconnect

## Quick Diagnosis

### 1. Check Current Metrics

```bash
# Prometheus queries
curl -s 'http://localhost:9090/api/v1/query?query=rate(websocket_broadcast_failure_total[5m])' | jq

# Calculate failure rate
curl -s 'http://localhost:9090/api/v1/query?query=rate(websocket_broadcast_failure_total[5m])/rate(websocket_broadcast_total[5m])' | jq
```

**Expected:** Failure rate should be < 0.01 (1%)
**Critical:** Failure rate > 0.05 (5%) - immediate intervention required

### 2. Check Container Health

```bash
# Verify API Gateway is running
docker ps | grep api_gateway

# Check logs for errors
docker logs ssf-backend_api_gateway_1 --tail 100 | grep -E "ERROR|WebSocket|broadcast"
```

**Look for:**
- `NameError: name 'manager' is not defined` ❌
- `WebSocketManager ist None` ❌
- `RuntimeError: WebSocketManager not initialized` ❌
- `Session XYZ has no connections` ⚠️ (may be expected)

### 3. Check WebSocket Connections

```bash
# Query active connections
curl -s 'http://localhost:9090/api/v1/query?query=websocket_connections_active' | jq

# Query sessions with connections
curl -s 'http://localhost:9090/api/v1/query?query=websocket_sessions_with_connections' | jq
```

**Expected:** `websocket_connections_active` should be > 0 if alert is firing
**Issue:** If connections = 0 but broadcasts > 0, broadcasting to dead sessions

## Root Cause Analysis

### Common Causes

#### 1. Container Restart (Most Common)

**Symptom:** Alert fires immediately after deployment/restart

**Cause:**
- WebSocketManager state lost during restart
- Old WebSocket connections not cleaned up
- Clients haven't reconnected yet

**Evidence:**
```bash
# Check container uptime
docker ps --format "{{.Names}}\t{{.Status}}" | grep api_gateway

# If uptime < 5 minutes, likely restart-related
```

**Resolution:**
- Wait 2-3 minutes for clients to auto-reconnect
- If persists, see "Container State Corruption" below

#### 2. WebSocketManager Initialization Failure

**Symptom:** All broadcasts fail from startup

**Cause:**
- `get_websocket_manager()` called before startup event
- Singleton not initialized in `app.py` lifespan

**Evidence:**
```bash
docker logs ssf-backend_api_gateway_1 | grep "WebSocketManager initialisiert"

# Should see:
# 🚀 WebSocketManager initialisiert (ID: 12345...)
```

**Resolution:**
```bash
# Restart container to trigger lifespan event
docker-compose restart api_gateway

# Verify initialization in logs
docker logs ssf-backend_api_gateway_1 --tail 20
```

#### 3. Session-Connection State Mismatch

**Symptom:** Metrics show sessions with connections but broadcasts fail

**Cause:**
- WebSocket connection closed but not removed from `session_connections`
- Heartbeat timeout not cleaning up stale connections

**Evidence:**
```promql
# Check for mismatch
websocket_sessions_with_connections > 0 and websocket_connections_active == 0
```

**Resolution:**
```bash
# Trigger manual cleanup via internal endpoint (if available)
curl -X POST http://localhost:8000/internal/websocket/cleanup

# Or restart to clear state
docker-compose restart api_gateway
```

#### 4. Network Issues (Client-Side)

**Symptom:** Intermittent failures, not consistent 100%

**Cause:**
- Clients behind poor network connections
- Firewall blocking WebSocket upgrades
- Load balancer timeout misconfig

**Evidence:**
```bash
# Check disconnect reasons
curl -s 'http://localhost:9090/api/v1/query?query=rate(websocket_disconnects_total[5m])' | jq

# High rate of "network_error" or "timeout"
```

**Resolution:**
- Check Traefik/Load Balancer WebSocket settings
- Verify no aggressive connection timeouts (should be > 60s)
- Test from different network to isolate client issues

#### 5. Code Regression (Dependency Injection Bug)

**Symptom:** Alert fires after code deployment

**Cause:**
- New route added without `manager: WebSocketManager = Depends(get_websocket_manager)`
- Function signature missing `manager` parameter
- Lazy initialization re-introduced

**Evidence:**
```bash
# Check recent git changes
git log --oneline --since="1 hour ago" services/api_gateway/

# Look for files mentioning broadcast or WebSocket
git diff HEAD~5 services/api_gateway/routes/session.py
```

**Resolution:**
```bash
# Rollback to previous version
git revert <commit-hash>
docker-compose up -d --force-recreate api_gateway

# Or apply hotfix
# Add missing dependency injection to route
```

## Step-by-Step Resolution

### Phase 1: Immediate Mitigation (0-5 minutes)

```bash
# 1. Check if simple restart fixes issue
docker-compose restart api_gateway

# 2. Wait 30 seconds for startup
sleep 30

# 3. Check if alert clears
curl -s 'http://localhost:9090/api/v1/query?query=rate(websocket_broadcast_failure_total[5m])' | jq

# 4. If still failing, check logs
docker logs ssf-backend_api_gateway_1 --tail 50
```

**If restart doesn't fix:** Proceed to Phase 2

### Phase 2: State Investigation (5-10 minutes)

```bash
# 1. Export current metrics
curl -s 'http://localhost:9090/api/v1/query?query={__name__=~"websocket.*"}' > /tmp/websocket_metrics.json

# 2. Check WebSocketManager state (if debug endpoint exists)
curl http://localhost:8000/internal/websocket/debug

# 3. Check Redis session state
docker exec ssf-backend_redis_1 redis-cli KEYS "session:*"

# 4. Compare active sessions vs connections
# Active sessions:
docker exec ssf-backend_redis_1 redis-cli KEYS "session:*" | wc -l

# Active connections:
curl -s 'http://localhost:9090/api/v1/query?query=websocket_connections_active' | jq -r '.data.result[0].value[1]'
```

**If mismatch detected:** Connections = 0 but sessions > 0 → Restart required

### Phase 3: Rollback Decision (10-15 minutes)

**Rollback if:**
- ✅ Alert started immediately after deployment
- ✅ Container restart doesn't fix
- ✅ No active WebSocket connections despite sessions
- ✅ Logs show `manager is None` errors

**Rollback procedure:**

```bash
# See: docs/deployment-rollback-procedure.md
cd /root/projects/ssf-backend

# 1. Get previous stable version
git log --oneline | head -20

# 2. Rollback code
git checkout <previous-commit-hash>

# 3. Rebuild and restart
docker-compose build api_gateway
docker-compose up -d --force-recreate api_gateway

# 4. Verify metrics
sleep 30
curl -s 'http://localhost:9090/api/v1/query?query=rate(websocket_broadcast_failure_total[5m])' | jq
```

### Phase 4: Root Cause Fix (Post-Incident)

**After service is restored:**

1. **Analyze logs:**
   ```bash
   docker logs ssf-backend_api_gateway_1 --since "1 hour ago" > /tmp/api_gateway_incident.log
   grep -E "ERROR|CRITICAL|broadcast|WebSocket" /tmp/api_gateway_incident.log
   ```

2. **Run E2E test:**
   ```bash
   cd /root/projects/ssf-backend
   python3 test_end_to_end_conversation.py

   # Should show:
   # ✅ Übersetzungsnachricht erfolgreich empfangen
   # Erfolgsquote: 100.0%
   ```

3. **Review code changes:**
   ```bash
   git diff <previous-stable-commit> services/api_gateway/

   # Focus on:
   # - routes/session.py (dependency injection)
   # - websocket.py (singleton initialization)
   # - app.py (lifespan events)
   ```

4. **Create post-mortem:**
   - Timeline of events
   - Root cause identified
   - Code fix applied
   - Prevention measures

## Monitoring Dashboard

**Grafana Dashboard:** "WebSocket Broadcasting Health"

**Key Panels:**
1. Broadcast Success Rate (should be > 99%)
2. Messages Delivered vs Failed
3. Active Connections per Session
4. Broadcast Latency P95

**Direct Link:** http://grafana-ssf.smart-village.solutions/d/websocket-broadcast

## Communication Template

### Incident Notification (Critical)

```
🚨 INCIDENT: WebSocket Broadcast Failures

STATUS: Investigating
IMPACT: Real-time translation messages not delivered
AFFECTED: All active sessions
START TIME: [timestamp]

We are investigating high broadcast failure rates.
Users may experience delayed or missing translations.

ACTIONS:
- Restarting API Gateway container
- Investigating WebSocketManager state
- Monitoring metrics for recovery

NEXT UPDATE: In 10 minutes
```

### Resolution Notification

```
✅ RESOLVED: WebSocket Broadcast Failures

STATUS: Resolved
DURATION: [X minutes]
ROOT CAUSE: [Container restart / Code regression / etc.]
RESOLUTION: [Restart / Rollback / etc.]

Broadcast success rate restored to 100%.
No further action required.

POST-MORTEM: [link to incident report]
```

## Prevention Measures

### Code Review Checklist

When reviewing WebSocket-related PRs:

- ✅ All routes use `manager: WebSocketManager = Depends(get_websocket_manager)`
- ✅ No global `websocket_manager` variables
- ✅ No lazy initialization in routes
- ✅ Tests include E2E broadcast validation
- ✅ Metrics added for new broadcast types

### Deployment Checklist

Before deploying WebSocket changes:

- ✅ Run E2E test in staging: `python3 test_end_to_end_conversation.py`
- ✅ Verify Prometheus metrics: `websocket_broadcast_success_total`
- ✅ Check container logs for initialization: `WebSocketManager initialisiert`
- ✅ Test reconnection behavior after restart
- ✅ Notify users if downtime expected

### Monitoring Improvements

**Additional Alerts to Consider:**

```yaml
# Alert if no broadcasts despite connections
- alert: WebSocketBroadcastNoActivityWithConnections
  expr: rate(websocket_broadcast_total[5m]) == 0 and websocket_connections_active > 2
  for: 10m

# Alert on manager initialization failures
- alert: WebSocketManagerNotInitialized
  expr: absent(websocket_manager_initialized)
  for: 1m
```

## Related Documents

- [ADR 001: WebSocket Singleton Pattern](../adr/001-websocket-singleton-pattern.md)
- [Deployment Guide: WebSocket Reconnection](../deployment-websocket-reconnection.md)
- [Rollback Procedure](./deployment-rollback-procedure.md)
- [WebSocket Architecture](../websocket-architecture.md)

## Contact

**On-Call:** Backend Team Rotation
**Slack Channel:** #backend-incidents
**PagerDuty:** Smart-Speech-Flow-Backend
**Escalation:** @backend-lead

---

**Version:** 1.0
**Last Tested:** 2025-11-05
**Next Review:** 2026-02-05
