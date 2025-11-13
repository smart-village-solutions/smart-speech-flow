# Rollback Plan: Pipeline Metadata Enhancement

**Feature:** WebSocket Message Metadata Enhancement
**Change ID:** `enhance-websocket-message-metadata`
**Version:** 2.0
**Date:** November 2025

## Overview

This document describes how to safely rollback the Pipeline Metadata Enhancement feature if issues arise in production.

## Rollback Scenarios

### Scenario 1: Full Rollback (Remove Feature Completely)

**When to use:** Critical bugs in metadata generation, performance degradation, or storage issues.

**Steps:**

1. **Stop Audio Cleanup Background Task** (if needed to preserve evidence):
   ```bash
   # SSH into api_gateway container
   docker exec -it ssf-backend-api_gateway-1 /bin/bash

   # Check background tasks
   ps aux | grep audio_cleanup
   ```

2. **Revert to Previous Docker Image:**
   ```bash
   # Stop current deployment
   docker-compose down

   # Checkout previous git commit (before metadata enhancement)
   git checkout <previous-commit-hash>

   # Rebuild and restart
   docker-compose build api_gateway
   docker-compose up -d
   ```

3. **Clean Up Audio Storage** (optional - saves disk space):
   ```bash
   # Remove all stored audio files
   rm -rf ./data/audio/original/*
   rm -rf ./data/audio/translated/*
   ```

**Impact:**
- ✅ Old clients continue working (backward compatible)
- ✅ No data migration needed
- ⚠️ Original audio URLs will return 404 (expected)
- ⚠️ `pipeline_metadata` field will be missing in new messages

### Scenario 2: Disable Audio Storage Only

**When to use:** Disk space issues, cleanup job failures, privacy concerns.

**Steps:**

1. **Modify `audio_storage.py`** to disable saving:
   ```python
   def save_original_audio(message_id: str, audio_base64: str) -> str:
       """Temporarily disabled - return placeholder URL"""
       logger.info(f"Audio storage disabled - skipping save for {message_id}")
       return None  # Will not include audio_url in metadata
   ```

2. **Restart API Gateway:**
   ```bash
   docker-compose restart api_gateway
   ```

**Impact:**
- ✅ Metadata still generated (timestamps, models, etc.)
- ✅ No disk usage for audio files
- ⚠️ `pipeline_metadata.input.audio_url` will be missing
- ✅ Cleanup job continues running (no-op)

### Scenario 3: Disable Metadata Generation

**When to use:** Metadata transformation bugs, serialization errors.

**Steps:**

1. **Modify `routes/session.py`** in `process_audio_input()` and `process_text_input()`:
   ```python
   # Comment out metadata transformation
   # pipeline_metadata = transform_pipeline_metadata(...)
   pipeline_metadata = None  # Disable metadata
   ```

2. **Restart API Gateway:**
   ```bash
   docker-compose restart api_gateway
   ```

**Impact:**
- ✅ Audio storage still works (files saved & cleaned up)
- ✅ Old behavior restored (no metadata in messages)
- ✅ Performance improvement (no transformation overhead)

## Backward Compatibility Guarantees

### Frontend Compatibility

**Old Frontends (pre-2.0):**
- ✅ Continue working without changes
- ✅ Ignore `pipeline_metadata` field (unknown field)
- ✅ Use existing fields (`audio_url`, `translated_text`, etc.)

**New Frontends (2.0+):**
- ⚠️ Must handle missing `pipeline_metadata` gracefully
- ⚠️ Must handle missing `original_audio_url` (404 after rollback)
- ✅ Can fallback to standard behavior

### Recommended Frontend Code Pattern

```typescript
// Safe metadata access
function getMetadata(message: Message): PipelineMetadata | null {
  if (!message.pipeline_metadata) {
    console.warn('No metadata available (old backend or feature disabled)');
    return null;
  }
  return message.pipeline_metadata;
}

// Safe original audio access
async function playOriginalAudio(url: string | undefined) {
  if (!url) {
    console.warn('Original audio URL not available');
    return;
  }

  try {
    const response = await fetch(url);
    if (response.status === 404) {
      showNotification('Audio nicht mehr verfügbar (>24h oder Feature deaktiviert)');
      return;
    }
    // ... play audio
  } catch (error) {
    console.error('Audio playback failed:', error);
  }
}
```

## Monitoring During Rollback

### Metrics to Watch

1. **WebSocket Connection Health:**
   ```promql
   websocket_connections_active
   websocket_broadcast_total
   ```

2. **Message Processing:**
   ```promql
   rate(http_requests_total{endpoint="/api/session/{id}/message"}[5m])
   ```

3. **Error Rates:**
   ```promql
   rate(http_requests_total{status=~"5.."}[5m])
   ```

### Expected Behavior After Rollback

- WebSocket connections remain stable
- Message processing continues normally
- No 500 errors related to missing metadata
- Prometheus metrics for audio storage may show zeros (expected)

## Testing After Rollback

### Smoke Tests

1. **Basic Message Flow:**
   ```bash
   # Send text message
   curl -X POST http://localhost:8000/api/session/{session_id}/message \
     -H "Content-Type: application/json" \
     -d '{"text":"Test","source_lang":"de","target_lang":"en","client_type":"admin"}'

   # Verify response (should NOT have pipeline_metadata)
   ```

2. **WebSocket Connection:**
   ```javascript
   const ws = new WebSocket('ws://localhost:8000/ws/{session_id}/admin');
   ws.onmessage = (event) => {
     const data = JSON.parse(event.data);
     console.log('Metadata present:', !!data.pipeline_metadata);
     // Should be false after rollback
   };
   ```

3. **Audio Endpoint:**
   ```bash
   # Should return 404 or old behavior
   curl -I http://localhost:8000/api/audio/input_test-123.wav
   ```

## Data Cleanup After Rollback

### Audio Files

**Option 1: Keep for historical analysis**
```bash
# Archive before deletion
tar -czf audio_archive_$(date +%Y%m%d).tar.gz ./data/audio/
mv audio_archive_*.tar.gz /backup/
```

**Option 2: Delete immediately**
```bash
# Free up disk space
rm -rf ./data/audio/original/*
rm -rf ./data/audio/translated/*
```

### Prometheus Metrics

- Metrics will naturally expire after retention period (default 15 days)
- No manual cleanup needed
- Old dashboards/alerts can be disabled in Grafana

## Communication Plan

### Internal Team Notification

```
Subject: Rollback - Pipeline Metadata Feature

Timeline: [Date/Time]
Duration: ~10 minutes
Impact: None (backward compatible)

Changes:
- Pipeline metadata removed from WebSocket messages
- Original audio storage disabled
- Old behavior restored

Action Required:
- Frontend teams: Verify graceful degradation
- DevOps: Monitor error rates for 24h
- Support: Inform users of missing "playback original" feature (if visible)

Rollback completed successfully ✅
```

### User-Facing Communication (if needed)

```
Temporäre Änderung: Die Funktion zum Abspielen der Original-Audioaufnahme
ist vorübergehend nicht verfügbar. Die Übersetzungen funktionieren weiterhin
normal. Wir arbeiten an einer Lösung.
```

## Re-Deployment Plan

### When to Re-Deploy

- ✅ Root cause identified and fixed
- ✅ Additional tests added
- ✅ Staged testing completed
- ✅ Performance benchmarks acceptable

### Staged Rollout

1. **Deploy to staging environment** - 48h monitoring
2. **Deploy to 10% of production** - Canary deployment
3. **Monitor key metrics** - 24h observation
4. **Full production deployment** - if no issues detected

## Contacts

- **Backend Team Lead:** [Name]
- **DevOps On-Call:** [Name]
- **Frontend Team Lead:** [Name]
- **Product Owner:** [Name]

## Rollback History

| Date | Reason | Duration | Impact |
|------|--------|----------|--------|
| - | - | - | - |

---

**Last Updated:** November 5, 2025
**Document Owner:** Backend Team
**Review Schedule:** Quarterly
