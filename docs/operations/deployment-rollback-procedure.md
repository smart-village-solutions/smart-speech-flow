# Deployment Rollback Procedure

**Version:** 1.0
**Last Updated:** 2025-11-05
**Audience:** DevOps, Backend Team

## Overview

This document describes the step-by-step procedure to rollback the Smart Speech Flow Backend API Gateway to a previous stable version in case of deployment failures or critical bugs.

## When to Rollback

### Immediate Rollback Criteria (P0 - Critical)

Rollback **IMMEDIATELY** if any of these occur after deployment:

- ❌ **WebSocket broadcast failure rate > 5%** for more than 2 minutes
- ❌ **All WebSocket connections failing** to establish
- ❌ **Container crash loop** (3+ restarts in 5 minutes)
- ❌ **500 errors on /api/session/* endpoints** > 10% for 2 minutes
- ❌ **Complete service outage** (health check failing)

### Scheduled Rollback Criteria (P1 - High)

Rollback **within 30 minutes** if:

- ⚠️ **Broadcast failure rate > 1%** sustained for 10+ minutes
- ⚠️ **Memory leak detected** (container memory > 2GB)
- ⚠️ **Performance degradation** (P95 latency > 5s)
- ⚠️ **Data corruption** in session state

### Do NOT Rollback For

These issues should be fixed forward:

- ✅ **Minor UI bugs** not affecting functionality
- ✅ **Non-critical log messages**
- ✅ **Documentation typos**
- ✅ **Cosmetic changes**

## Pre-Rollback Checklist

Before initiating rollback:

1. **Verify incident is deployment-related:**
   ```bash
   # Check deployment time
   docker inspect ssf-backend_api_gateway_1 | jq '.[0].State.StartedAt'

   # Compare with alert start time
   # If alert started within 5 minutes of deployment → likely related
   ```

2. **Capture diagnostic data:**
   ```bash
   # Container logs
   docker logs ssf-backend_api_gateway_1 --since "30m" > /tmp/pre_rollback_logs.txt

   # Prometheus metrics
   curl -s 'http://localhost:9090/api/v1/query?query={__name__=~"websocket.*"}' > /tmp/pre_rollback_metrics.json

   # Current container state
   docker inspect ssf-backend_api_gateway_1 > /tmp/pre_rollback_inspect.json
   ```

3. **Identify rollback target:**
   ```bash
   # Show recent commits
   git log --oneline --since="2 days ago" services/api_gateway/

   # Find last known good version (tagged or from release notes)
   git tag | grep "api-gateway" | tail -5
   ```

4. **Notify stakeholders:**
   - Post in #backend-incidents Slack channel
   - Tag on-call engineer
   - Update status page if customer-facing

## Rollback Procedure

### Phase 1: Code Rollback (2-5 minutes)

```bash
# 1. Navigate to project directory
cd /root/projects/ssf-backend

# 2. Check current version
git rev-parse --short HEAD
# Example output: a1b2c3d

# 3. Identify target version (last stable deployment)
# Option A: Use git tag
git checkout tags/api-gateway-v1.0.0

# Option B: Use commit hash from incident notes
git checkout f3e4d5c

# Option C: Revert specific commit(s)
git log --oneline | head -10
git revert --no-commit a1b2c3d..HEAD
git commit -m "Rollback: Revert changes causing broadcast failures"

# 4. Verify code state
git status
git log --oneline | head -5
```

**⚠️ IMPORTANT:** Do NOT use `git reset --hard` in production - use `git revert` or `git checkout` to maintain audit trail.

### Phase 2: Container Rebuild (3-5 minutes)

```bash
# 1. Build new image from rolled-back code
docker-compose build api_gateway

# Expected output:
# [+] Building 45.2s (15/15) FINISHED
# Successfully tagged ssf-backend_api_gateway:latest

# 2. Verify image was created
docker images | grep api_gateway

# Should see new image with "seconds ago" or "minutes ago"
```

### Phase 3: Container Replacement (1-2 minutes)

```bash
# 1. Stop current container
docker-compose stop api_gateway

# 2. Remove old container
docker-compose rm -f api_gateway

# 3. Start new container from rolled-back image
docker-compose up -d api_gateway

# Alternative one-liner:
docker-compose up -d --force-recreate --no-deps api_gateway

# 4. Verify container started
docker ps | grep api_gateway

# Should show "Up X seconds"
```

**⚠️ Downtime:** This causes ~10-30 seconds of downtime. WebSocket clients will auto-reconnect.

### Phase 4: Verification (5-10 minutes)

#### 4.1 Container Health

```bash
# Check container is running
docker ps --filter "name=api_gateway" --format "{{.Status}}"

# Should show: "Up X seconds (healthy)" or "Up X seconds"

# Check initialization logs
docker logs ssf-backend_api_gateway_1 --tail 50 | grep -E "WebSocketManager|initialisiert|ready"

# Expected:
# 🚀 WebSocketManager initialisiert (ID: 12345...)
# ✅ API Gateway bereit
```

#### 4.2 Health Endpoint

```bash
# HTTP health check
curl -s http://localhost:8000/health | jq

# Expected response:
{
  "status": "healthy",
  "services": {
    "ASR": "healthy",
    "Translation": "healthy",
    "TTS": "healthy"
  }
}

# If 503 or timeout → container not fully started, wait 30s and retry
```

#### 4.3 Metrics Validation

```bash
# Check broadcast failure rate
curl -s 'http://localhost:9090/api/v1/query?query=rate(websocket_broadcast_failure_total[5m])/rate(websocket_broadcast_total[5m])' | jq -r '.data.result[0].value[1]'

# Expected: "0" or very small number < 0.01

# Check active connections
curl -s 'http://localhost:9090/api/v1/query?query=websocket_connections_active' | jq

# Should show connections increasing as clients reconnect
```

#### 4.4 End-to-End Test

```bash
# Run automated E2E test
cd /root/projects/ssf-backend
python3 test_end_to_end_conversation.py

# Expected output:
# ✅ Übersetzungsnachricht erfolgreich empfangen
# Erfolgsquote: 100.0%
# Nachrichten gesamt: 2
# WebSocket Timeouts: 0

# If test fails → rollback unsuccessful, investigate further
```

#### 4.5 Monitor for Stability (10 minutes)

```bash
# Watch metrics in real-time
watch -n 5 'curl -s "http://localhost:9090/api/v1/query?query=rate(websocket_broadcast_failure_total[5m])" | jq -r ".data.result[0].value[1] // 0"'

# Monitor container logs
docker logs ssf-backend_api_gateway_1 -f

# Watch for:
# ✅ No ERROR messages
# ✅ Heartbeat messages flowing
# ✅ Broadcast success logs
```

### Phase 5: Post-Rollback Actions

#### 5.1 Update Incident Tracker

```markdown
## Incident Timeline

**14:05** - Alert fired: WebSocketBroadcastFailureRateHigh
**14:07** - Investigation started
**14:12** - Rollback decision made
**14:15** - Code rolled back to commit f3e4d5c
**14:18** - Container restarted with rolled-back code
**14:20** - Metrics validated - 0% failure rate
**14:25** - E2E test passed
**14:30** - Monitoring for stability
**14:40** - Incident resolved

## Root Cause

[To be determined - requires code review]

## Resolution

Rolled back to previous stable version (f3e4d5c).
Problematic commit (a1b2c3d) reverted.
```

#### 5.2 Notify Stakeholders

```
✅ ROLLBACK COMPLETE: API Gateway

Previous deployment has been rolled back due to WebSocket broadcast failures.

CURRENT VERSION: f3e4d5c (stable)
PROBLEMATIC VERSION: a1b2c3d (rolled back)
METRICS: 0% broadcast failures, 100% success rate
DOWNTIME: ~2 minutes

System is now stable. Root cause analysis in progress.
```

#### 5.3 Root Cause Analysis

```bash
# Compare rolled-back changes
git diff f3e4d5c a1b2c3d services/api_gateway/

# Focus on:
# - Dependency injection changes
# - WebSocketManager initialization
# - Broadcasting logic
# - Route signatures

# Create post-mortem document
cp docs/templates/postmortem.md docs/incidents/2025-11-05-broadcast-failure.md
```

## Rollback Scenarios & Solutions

### Scenario 1: Docker Compose Bug (KeyError: 'ContainerConfig')

**Symptom:**
```
ERROR: KeyError: 'ContainerConfig'
ERROR: for api_gateway  Cannot create container for service api_gateway
```

**Solution:**
```bash
# Workaround: Manual container management
docker stop ssf-backend_api_gateway_1
docker rm ssf-backend_api_gateway_1

# Recreate without dependencies
docker-compose up -d --no-deps api_gateway

# Manually start dependencies if stopped
docker start ssf-backend_redis_1
docker start ssf-backend_ollama_1

# Verify all containers running
docker ps
```

### Scenario 2: Database Migration Required

**Symptom:**
```
alembic.util.exc.CommandError: Target database is not up to date.
```

**Solution:**
```bash
# Rollback database migrations first
docker exec ssf-backend_api_gateway_1 alembic downgrade -1

# Then proceed with code rollback
# (Standard procedure above)
```

### Scenario 3: Redis State Corruption

**Symptom:**
```
redis.exceptions.ResponseError: WRONGTYPE Operation against a key holding the wrong kind of value
```

**Solution:**
```bash
# Backup Redis data
docker exec ssf-backend_redis_1 redis-cli --rdb /tmp/backup.rdb

# Flush corrupted keys (CAUTION: loses active sessions)
docker exec ssf-backend_redis_1 redis-cli FLUSHDB

# Restart API Gateway
docker-compose restart api_gateway
```

### Scenario 4: Image Tag Mismatch

**Symptom:**
Container starts but runs old code despite rebuild

**Solution:**
```bash
# Force image rebuild with no cache
docker-compose build --no-cache api_gateway

# Verify image creation time
docker images --format "{{.Repository}}:{{.Tag}}\t{{.CreatedSince}}" | grep api_gateway

# If still old, remove image completely
docker rmi ssf-backend_api_gateway:latest
docker-compose build api_gateway
docker-compose up -d api_gateway
```

## Emergency Contacts

**Immediate Support:**
- On-Call Engineer: See PagerDuty rotation
- Slack: #backend-incidents (mention @backend-oncall)

**Escalation Path:**
1. Backend Team Lead: @backend-lead
2. CTO: @cto
3. DevOps Manager: @devops-manager

**External Vendors:**
- Redis Support: (if Redis-related)
- Docker Support: (if container-related)

## Rollback Testing

### Quarterly Rollback Drill

**Schedule:** First Monday of each quarter
**Duration:** 30 minutes
**Participants:** DevOps + Backend Team

**Procedure:**
1. Deploy intentionally broken code to staging
2. Trigger alert
3. Execute rollback procedure
4. Validate metrics
5. Document lessons learned

**Acceptance Criteria:**
- Rollback completed in < 15 minutes
- Zero manual intervention required
- Metrics return to baseline
- E2E test passes

## Version History

| Version | Date       | Changes                          | Author       |
|---------|------------|----------------------------------|--------------|
| 1.0     | 2025-11-05 | Initial rollback procedure       | Backend Team |

## Related Documents

- [Deployment Guide: WebSocket Reconnection](./deployment-websocket-reconnection.md)
- [Runbook: WebSocket Broadcast Failures](./runbooks/websocket-broadcast-failures.md)
- [ADR 001: WebSocket Singleton Pattern](./adr/001-websocket-singleton-pattern.md)

---

**Approval:** DevOps Team
**Review Date:** 2026-02-05
