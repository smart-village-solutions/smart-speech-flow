# Code Review Request: WebSocket Message Metadata Enhancement

## Change Summary

**Change Proposal:** `enhance-websocket-message-metadata`
**Status:** Implementation Complete - Ready for Review
**Tasks Completed:** 78/79 (98.7%)
**Remaining:** Code review approval only

## Overview

This change adds comprehensive pipeline metadata to all WebSocket messages and introduces original audio file storage with 24-hour retention. The enhancement provides full transparency into pipeline processing while maintaining backward compatibility.

## Key Features Implemented

### 1. Pipeline Metadata (Always Present)
- **Input metadata:** Source language, input type (audio/text), audio URL
- **Step tracking:** ASR, Translation, Refinement, TTS
- **Timing data:** ISO 8601 timestamps, duration in milliseconds
- **Backward compatible:** Old clients ignore metadata gracefully

### 2. Original Audio Storage
- **Storage path:** `/data/audio/original/input_{message_id}.wav`
- **Retention:** 24 hours (configurable via `AUDIO_RETENTION_HOURS`)
- **Cleanup:** Hourly background job with Prometheus metrics
- **Access:** GET `/api/audio/input_{message_id}.wav`

### 3. Monitoring & Observability
- **Prometheus metrics:**
  - `audio_storage_disk_usage_bytes` (by type: original/translated)
  - `audio_files_total` (by type)
  - `audio_cleanup_deleted_files_total` (by type)
- **Grafana dashboard:** 7 panels covering disk usage, cleanup, pipeline performance
- **Alerts:** Disk usage warnings (>80%, >95%), cleanup failures

## Files Changed

### Core Implementation (Phase 0-3)
```
services/api_gateway/app/utils/audio_storage.py (NEW)
- save_original_audio()
- get_original_audio_path()
- cleanup_old_audio_files()
- get_audio_storage_metrics()

services/api_gateway/app.py (MODIFIED)
- Added background task: cleanup_audio_files_task()
- Added Prometheus metrics endpoint
- Added audio cleanup metrics

services/api_gateway/routes/session.py (MODIFIED)
- transform_pipeline_metadata() - converts debug_info to metadata
- POST /api/session/{id}/audio - saves original audio
- POST /api/session/{id}/text - adds metadata
- GET /api/audio/input_{message_id}.wav - retrieves original audio

services/api_gateway/session_manager.py (MODIFIED)
- SessionMessage.pipeline_metadata (Optional[Dict])
- SessionMessage.original_audio_url (Optional[str])
- to_dict() includes new fields

services/api_gateway/pipeline_logic.py (MODIFIED)
- Audio pipeline returns debug_info with steps
- Text pipeline returns debug_info with steps
```

### Tests (Phase 4-5)
```
tests/test_pipeline_metadata_enhancement.py (NEW)
- 8/8 unit tests passing
- Tests transform_pipeline_metadata()
- Tests SessionMessage serialization

tests/test_pipeline_metadata_integration.py (NEW)
- 15/17 integration tests passing (2 skipped for E2E)
- Tests audio/text pipelines
- Tests cleanup job and metrics

tests/test_end_to_end_conversation.py (NEW)
- 8/8 E2E tests passing
- Tests metadata presence, structure, timestamps
- Tests original audio storage and retrieval
```

### Documentation (Phase 6)
```
docs/frontend_api.md (UPDATED)
- Section 8: Complete pipeline metadata documentation
- Examples for audio and text pipelines
- TypeScript interfaces
- Privacy and retention policy

docs/WEBSOCKET_MESSAGE_ROLES.md (UPDATED)
- Added pipeline_metadata to all message examples
- New section "Pipeline Metadata" with complete spec
- Updated TypeScript interfaces

openapi.yaml (NEW)
- Complete OpenAPI 3.0.3 specification
- Schemas: MessageResponse, PipelineMetadata, PipelineStep
- All endpoints documented
```

### Configuration (Phase 7-8)
```
docker-compose.yml (MODIFIED)
- Volume mount: ./data/audio:/data/audio
- Environment variables: AUDIO_STORAGE_PATH, AUDIO_RETENTION_HOURS

.env.example (MODIFIED)
- AUDIO_STORAGE_PATH=/data/audio
- AUDIO_RETENTION_HOURS=24
- ENABLE_PIPELINE_METADATA=true

.gitignore (MODIFIED)
- /data/audio/

monitoring/alert_rules.yml (MODIFIED)
- AudioStorageDiskUsageHigh (>80%)
- AudioStorageDiskUsageCritical (>95%)
- AudioCleanupFailures

monitoring/grafana/dashboards/audio-storage-pipeline.json (NEW)
- 7 panels for monitoring
```

### Performance & Benchmarks (Phase 7)
```
benchmark_performance.py (NEW)
- Benchmark 1: Message size +271.7% (364 → 1,353 bytes) ✅
- Benchmark 2: Serialization 4.68μs per message ✅
- Benchmark 3: 100 sessions, 1000 messages, 24.69MB ✅
- Benchmark 5: Disk I/O 1265MB/s throughput ✅

performance_benchmark_results.json (NEW)
- Complete benchmark results with timestamps
```

### Rollback & Deployment
```
openspec/changes/enhance-websocket-message-metadata/ROLLBACK.md (NEW)
- 3 rollback scenarios documented
- Monitoring guidelines
- Re-deployment strategy
```

## Testing Coverage

### Unit Tests (8/8 passing)
- `test_transform_pipeline_metadata_valid_input()`
- `test_transform_pipeline_metadata_missing_fields()`
- `test_transform_pipeline_metadata_iso8601_timestamps()`
- `test_session_message_with_metadata_serialization()`
- `test_session_message_with_metadata_deserialization()`
- `test_session_message_backward_compatible()`
- `test_session_message_original_audio_url()`
- `test_session_message_to_dict_includes_metadata()`

### Integration Tests (15/17 passing, 2 skipped)
- Audio pipeline with metadata ✅
- Text pipeline with metadata ✅
- Refinement step disabled ✅
- Original audio storage ✅
- Audio cleanup (24h) ✅
- Prometheus metrics ✅
- Disk usage monitoring ✅

### E2E Tests (8/8 passing)
- Metadata always present ✅
- Pipeline steps validation ✅
- ISO 8601 timestamps ✅
- Duration calculations ✅
- Original audio URL ✅
- Audio endpoint ✅
- Text pipeline (no original audio) ✅
- Backward compatibility ✅

## Performance Results

### Message Size Impact
- **Legacy:** 364 bytes
- **New:** 1,353 bytes
- **Increase:** +271.7% (acceptable for metadata richness)

### Serialization Overhead
- **Average:** 4.68μs per message (negligible)

### Concurrent Sessions
- **Sessions:** 100 concurrent
- **Messages:** 1,000 total
- **Memory:** 24.69MB (0.25MB per session)

### Disk I/O
- **Write:** 0.03ms per file
- **Read:** 0.01ms per file
- **Throughput:** 1,265MB/s
- **Verdict:** Fast enough for real-time storage

## Backward Compatibility

### Old Clients (No Code Changes Required)
```javascript
// Old client code continues to work
socket.on('message', (data) => {
  console.log(data.text); // Works fine
  console.log(data.audio_url); // Works fine
  // data.pipeline_metadata is ignored (undefined check prevents errors)
});
```

### New Clients (Can Opt-In)
```typescript
interface ChatMessage {
  // ... existing fields
  pipeline_metadata?: PipelineMetadata; // Optional consumption
}
```

## Security Considerations

### Audio File Storage
- **Isolation:** Files stored in `/data/audio/` (not web-accessible)
- **Access:** Only via authenticated API endpoint
- **Retention:** Automatic deletion after 24h
- **Disk limits:** Alerts trigger at 80% and 95% usage

### Metadata Privacy
- No sensitive data in metadata (only processing timing)
- Original text/audio not duplicated in metadata

## Migration Strategy

### Phase 1: Deploy (Low Risk)
1. Deploy updated API Gateway with volume mount
2. Old clients ignore `pipeline_metadata` (backward compatible)
3. Monitor disk usage via Grafana dashboard

### Phase 2: Frontend Adoption (Optional)
1. Frontend teams opt-in to using `pipeline_metadata`
2. Implement performance monitoring
3. Add debugging features

### Frontend Migration Guide

No feature flags or headers required - metadata is always present in responses.

#### Phase 1: Ignore (No Code Changes)
Old clients continue to work unchanged. The `pipeline_metadata` field is simply ignored:

```javascript
// Existing code works without modifications
socket.on('message', (data) => {
  console.log(data.text);           // ✅ Works
  console.log(data.audio_url);      // ✅ Works
  // data.pipeline_metadata exists but is not accessed
});
```

#### Phase 2: Read-Only Monitoring (Low Risk)
Start consuming metadata for logging and debugging:

```javascript
socket.on('message', (data) => {
  // Existing functionality
  displayMessage(data.text, data.audio_url);

  // NEW: Optional performance monitoring
  if (data.pipeline_metadata) {
    console.log('Pipeline duration:', data.pipeline_metadata.total_duration_ms + 'ms');

    // Track slow pipelines
    if (data.pipeline_metadata.total_duration_ms > 3000) {
      console.warn('Slow pipeline detected', data.pipeline_metadata);
    }
  }
});
```

#### Phase 3: Performance Analytics (Recommended)
Send metrics to analytics platform:

```typescript
interface ChatMessage {
  // ... existing fields
  pipeline_metadata?: PipelineMetadata;
}

socket.on('message', (data: ChatMessage) => {
  displayMessage(data.text, data.audio_url);

  // Track metrics
  if (data.pipeline_metadata) {
    analytics.track('pipeline.duration', {
      total_ms: data.pipeline_metadata.total_duration_ms,
      input_type: data.pipeline_metadata.input.type,
      steps: data.pipeline_metadata.steps.map(s => s.name)
    });

    // Track individual step performance
    data.pipeline_metadata.steps.forEach(step => {
      analytics.track(`pipeline.step.${step.name}`, {
        duration_ms: step.duration_ms
      });
    });
  }
});
```

#### Phase 4: User-Facing Features (Advanced)
Add UI features based on metadata:

```javascript
socket.on('message', (data) => {
  displayMessage(data.text, data.audio_url);

  // Show original audio playback button (only for messages user sent)
  if (data.original_audio_url && currentUser.role === data.sender) {
    showOriginalAudioButton(data.original_audio_url);
  }

  // Show processing time in debug mode
  if (DEBUG_MODE && data.pipeline_metadata) {
    showProcessingTime(data.pipeline_metadata.total_duration_ms);
  }

  // Highlight slow translations
  const translationStep = data.pipeline_metadata?.steps.find(s => s.name === 'translation');
  if (translationStep && translationStep.duration_ms > 1000) {
    showSlowTranslationIndicator();
  }
});
```

#### Error Handling for Original Audio

```javascript
async function playOriginalAudio(audioUrl) {
  try {
    const response = await fetch(audioUrl);

    if (response.status === 404) {
      showNotification('Audio expired (>24h retention policy)', 'info');
    } else if (response.status === 403) {
      showNotification('Access denied', 'error');
    } else if (response.status === 410) {
      showNotification('Audio permanently deleted', 'info');
    } else if (response.ok) {
      const audioBlob = await response.blob();
      playAudio(audioBlob);
    } else {
      showNotification('Failed to load audio', 'error');
    }
  } catch (error) {
    console.error('Audio playback error:', error);
    showNotification('Network error', 'error');
  }
}
```

**Migration Timeline:**
- **Week 1-2:** Phase 1 (no changes, verify backward compatibility)
- **Week 3-4:** Phase 2 (read-only logging)
- **Week 5-6:** Phase 3 (analytics integration)
- **Week 7+:** Phase 4 (user-facing features, optional)

### Rollback Plan
- **Full rollback:** Revert to previous Docker image (metadata disappears, clients work)
- **Audio-only rollback:** Stop cleanup job, disable audio storage
- **Metadata-only rollback:** Remove audio storage, keep metadata

## Review Checklist

Please verify:

- [ ] **Code Quality**
  - [ ] Functions are well-named and documented
  - [ ] No code duplication
  - [ ] Error handling is comprehensive
  - [ ] Type hints used consistently

- [ ] **Testing**
  - [ ] All 31 tests passing (8 unit + 15 integration + 8 E2E)
  - [ ] Test coverage is comprehensive
  - [ ] Edge cases are covered

- [ ] **Documentation**
  - [ ] API documentation is accurate
  - [ ] Examples are correct and helpful
  - [ ] Privacy policy is clear
  - [ ] Rollback plan is complete

- [ ] **Performance**
  - [ ] Benchmarks show acceptable impact
  - [ ] No memory leaks
  - [ ] Disk I/O is efficient
  - [ ] Cleanup job works correctly

- [ ] **Security**
  - [ ] Audio files are isolated
  - [ ] No sensitive data leaks
  - [ ] Disk space is monitored
  - [ ] Retention policy is enforced

- [ ] **Monitoring**
  - [ ] Prometheus metrics are correct
  - [ ] Grafana dashboard is useful
  - [ ] Alerts are properly configured

- [ ] **Deployment**
  - [ ] Docker configuration is correct
  - [ ] Environment variables are documented
  - [ ] Volume mounts are secure
  - [ ] Rollback plan is viable
  - [ ] Disk space monitoring configured
  - [ ] Backup strategy defined (if applicable)
  - [ ] Resource limits set (memory, CPU)

## Additional Documentation

### Deployment Risks & Mitigation
See [DEPLOYMENT.md](./DEPLOYMENT.md) for:
- Volume mount risks (disk full, permissions, backups)
- Production-ready docker-compose.yml with resource limits
- tmpfs configuration for temporary uploads
- Pre-deployment checklist
- Post-deployment verification scripts
- Disaster recovery procedures
- Critical metrics to monitor in first 24h

### API Error Codes
See [openapi.yaml](../../../openapi.yaml) for complete error documentation:
- **404 Not Found:** Audio expired (>24h) or never existed
- **403 Forbidden:** Different client attempting access
- **410 Gone:** Explicitly deleted (GDPR compliance)
- **500 Internal Server Error:** Storage system failure

Each error includes:
- HTTP status code
- JSON error response with message
- Additional context (e.g., retention_policy, deleted_at)

## Deployment Commands

```bash
# Build and deploy
docker-compose build api_gateway
docker-compose up -d api_gateway

# Verify deployment
curl http://localhost:8000/health
curl http://localhost:8000/metrics | grep audio_storage

# Monitor logs
docker-compose logs -f api_gateway

# Check audio storage
docker exec -it api_gateway ls -lh /data/audio/original/
docker exec -it api_gateway ls -lh /data/audio/translated/
```

## Questions for Reviewers

1. **Metadata Structure:** Is the `pipeline_metadata` structure intuitive for frontend developers?
2. **Error Handling:** Are there edge cases in `transform_pipeline_metadata()` that need coverage?
3. **Performance:** Is the +272% message size increase acceptable given the metadata richness?
4. **Security:** Are there additional security considerations for audio file storage?
5. **Documentation:** Is the migration guide clear enough for frontend teams?

## Contact

For questions or clarifications, please reach out to the backend team.

---

**Generated:** 2025-11-05
**Change ID:** enhance-websocket-message-metadata
**Status:** ✅ Ready for Review
