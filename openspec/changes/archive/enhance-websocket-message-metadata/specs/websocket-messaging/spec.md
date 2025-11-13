# WebSocket Messaging - Specification Delta

**Change ID:** `enhance-websocket-message-metadata`
**Capability:** `websocket-messaging`

## ADDED Requirements

### Requirement: WebSocket Messages MUST Include Pipeline Metadata

The system MUST include pipeline metadata in all WebSocket messages of type `message`.

**ID:** `wsm-metadata-001`
**Priority:** High

#### Scenario: Audio message includes all pipeline steps

**Given** an admin sends an audio message
**When** the pipeline processing completes
**Then** the WebSocket message MUST contain `pipeline_metadata` field with `input`, `steps`, and timing information

### Requirement: System MUST Store Original Audio Files Persistently

The system MUST store original audio files persistently on local filesystem at `/data/audio/original/`.

**ID:** `wsm-audio-storage-001`
**Priority:** High

#### Scenario: Original audio file is saved to disk

**Given** a client sends an audio message
**When** the system receives the audio file
**Then** the file MUST be saved to `/data/audio/original/input_{message_id}.wav`

### Requirement: System MUST Delete Audio Files After 24 Hours

The system MUST delete audio files after 24 hours.

**ID:** `wsm-audio-cleanup-001`
**Priority:** High

#### Scenario: Audio files older than 24 hours are deleted

**Given** an audio file was created 25 hours ago
**When** the cleanup job runs
**Then** the file MUST be deleted from disk

### Requirement: System MUST Run Hourly Cleanup Job

The system MUST run an hourly background job to clean up old audio files.

**ID:** `wsm-cleanup-job-001`
**Priority:** Medium

#### Scenario: Cleanup job executes every hour

**Given** the system is running
**When** one hour has passed
**Then** the cleanup job MUST execute and remove files older than 24 hours

### Requirement: Timestamps MUST Use ISO 8601 UTC Format

The system MUST use ISO 8601 UTC format for all timestamps in pipeline metadata.

**ID:** `wsm-timestamp-format-001`
**Priority:** High

#### Scenario: Timestamps are in correct format

**Given** a WebSocket message with pipeline metadata
**Then** all timestamps MUST match format `YYYY-MM-DDTHH:mm:ss.sssZ`

### Requirement: System MUST Provide Disk Space Monitoring

The system MUST expose Prometheus metrics for audio storage monitoring.

**ID:** `wsm-monitoring-001`
**Priority:** Medium

#### Scenario: Prometheus metrics are available

**Given** the system is running
**When** Prometheus scrapes `/metrics`
**Then** metrics `audio_storage_disk_usage_bytes`, `audio_files_total`, and `audio_cleanup_deleted_files_total` MUST be present

### Requirement: Pipeline Steps MUST Include Model Information

The system MUST include ML model information in pipeline step outputs.

**ID:** `wsm-model-info-001`
**Priority:** Low

#### Scenario: Translation step includes model name

**Given** a message is translated
**Then** the translation step MUST include `output.model` field with value like `m2m100_1.2B`

## MODIFIED Requirements

### Requirement: WebSocket Messages MUST Support Enhanced Structure

The system MUST support the enhanced WebSocket message structure including pipeline metadata.

**ID:** `wsm-message-001`
**Priority:** Critical

#### Scenario: Enhanced message structure is valid

**Given** a message is sent through the pipeline
**When** the WebSocket broadcast occurs
**Then** the message MUST include all existing fields plus `pipeline_metadata` field
