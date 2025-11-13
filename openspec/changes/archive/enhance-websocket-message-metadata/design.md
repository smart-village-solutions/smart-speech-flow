# Design: Enhance WebSocket Message Metadata

**Change ID:** `enhance-websocket-message-metadata`
**Status:** 🟡 Draft

## Architecture Overview

### Current State

```
┌─────────────┐
│   Client    │ Sends Audio/Text
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────────────┐
│         HTTP Endpoint                       │
│  POST /api/session/{id}/message             │
└──────┬──────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────┐
│         Pipeline Logic                      │
│  ┌─────────┐  ┌────────────┐  ┌──────┐     │
│  │   ASR   │→ │ Translation│→ │ TTS  │     │
│  └─────────┘  └────────────┘  └──────┘     │
│                                             │
│  Returns: {                                 │
│    asr_text: "...",                         │
│    translation_text: "...",                 │
│    audio_bytes: b"...",                     │
│    debug: {...}  ← NOT STORED/SENT         │
│  }                                          │
└──────┬──────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────┐
│      SessionMessage Created                 │
│  - id                                       │
│  - original_text                            │
│  - translated_text                          │
│  - audio_base64                             │
│  - timestamp                                │
│  ❌ NO pipeline_metadata                    │
└──────┬──────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────┐
│      WebSocket Broadcasting                 │
│  {                                          │
│    type: "message",                         │
│    text: "...",                             │
│    audio_url: "...",                        │
│    ❌ NO pipeline_metadata                  │
│  }                                          │
└──────┬──────────────────────────────────────┘
       │
       ▼
┌─────────────┐
│   Client    │ Receives ONLY final result
└─────────────┘
```

### Proposed State

```
┌─────────────┐
│   Client    │ Sends Audio/Text
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────────────┐
│         HTTP Endpoint                       │
│  POST /api/session/{id}/message             │
│  ✅ Store original audio as input_*.wav     │
└──────┬──────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────┐
│         Pipeline Logic                      │
│  ┌─────────┐  ┌────────────┐  ┌──────┐     │
│  │   ASR   │→ │ Translation│→ │ TTS  │     │
│  └─────────┘  └────────────┘  └──────┘     │
│  ✅ Each step records:                      │
│     - started_at (ISO timestamp)            │
│     - completed_at (ISO timestamp)          │
│     - duration_ms                           │
│     - input/output data                     │
│                                             │
│  Returns: {                                 │
│    asr_text: "...",                         │
│    translation_text: "...",                 │
│    audio_bytes: b"...",                     │
│    debug: {...},                            │
│    ✅ pipeline_metadata: {...}              │
│  }                                          │
└──────┬──────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────┐
│      SessionMessage Created                 │
│  - id                                       │
│  - original_text                            │
│  - translated_text                          │
│  - audio_base64                             │
│  - timestamp                                │
│  ✅ pipeline_metadata: {...}                │
│  ✅ original_audio_url: "/api/audio/input_*"│
└──────┬──────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────┐
│      WebSocket Broadcasting                 │
│  {                                          │
│    type: "message",                         │
│    text: "...",                             │
│    audio_url: "...",                        │
│    ✅ pipeline_metadata: {                  │
│         input: {...},                       │
│         steps: [...],                       │
│         total_duration_ms: 5000             │
│       }                                     │
│  }                                          │
└──────┬──────────────────────────────────────┘
       │
       ▼
┌─────────────┐
│   Client    │ Receives complete metadata
└─────────────┘    + decides what to show
```

## Data Structures

### Pipeline Metadata Schema

```typescript
interface PipelineMetadata {
  // Original Input
  input: {
    type: "audio" | "text";
    audio_url?: string;           // Only for audio pipeline
    source_lang: string;
  };

  // Pipeline Steps
  steps: PipelineStep[];

  // Summary
  total_duration_ms: number;
  pipeline_started_at: string;    // ISO 8601
  pipeline_completed_at: string;  // ISO 8601
}

interface PipelineStep {
  name: "asr" | "translation" | "refinement" | "tts";
  input: Record<string, any>;
  output: Record<string, any>;
  started_at: string;             // ISO 8601
  completed_at: string;           // ISO 8601
  duration_ms: number;
  error?: string;                 // If step failed
}
```

### Backend: Debug Info → Metadata Transformation

Current `debug_info` structure (from pipeline_logic.py):

```python
debug_info = {
    "frontend_input": {
        "source_lang": "de",
        "target_lang": "en",
        "text_length": 50
    },
    "steps": [
        {
            "step": "ASR",           # ← Inconsistent naming
            "input": {...},
            "output": "...",
            "error": None,
            "duration": 2.5          # ← Only duration, no timestamps
        },
        {
            "step": "Translation",
            "input": {...},
            "output": "...",
            "error": None,
            "duration": 0.5
        }
    ],
    "total_duration": 5.0
}
```

New transformation function:

```python
def transform_debug_to_metadata(
    debug_info: Dict[str, Any],
    original_audio_url: Optional[str] = None,
    input_type: str = "audio"
) -> Dict[str, Any]:
    """
    Transform pipeline debug_info to metadata format.

    Args:
        debug_info: Output from process_wav() or process_text_pipeline()
        original_audio_url: URL to original input audio (if applicable)
        input_type: "audio" or "text"

    Returns:
        Metadata dict matching PipelineMetadata schema
    """
    steps = debug_info.get("steps", [])

    # Calculate absolute timestamps
    pipeline_start = datetime.now(timezone.utc)
    current_time = pipeline_start

    transformed_steps = []
    for step in steps:
        step_duration = timedelta(seconds=step.get("duration", 0))
        started_at = current_time
        completed_at = current_time + step_duration

        transformed_steps.append({
            "name": step["step"].lower(),  # ASR → asr
            "input": step.get("input", {}),
            "output": step.get("output", {}),
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "duration_ms": int(step.get("duration", 0) * 1000),
            "error": step.get("error")
        })

        current_time = completed_at

    return {
        "input": {
            "type": input_type,
            "audio_url": original_audio_url,
            "source_lang": debug_info.get("frontend_input", {}).get("source_lang")
        },
        "steps": transformed_steps,
        "total_duration_ms": int(debug_info.get("total_duration", 0) * 1000),
        "pipeline_started_at": pipeline_start.isoformat(),
        "pipeline_completed_at": current_time.isoformat()
    }
```

## Implementation Details

### 1. Original Audio Storage

**Problem:** Original audio is currently only in request, not persisted.

**Solution:** Store original audio with unique URL

```python
# In routes/session.py - process_audio_input()

async def process_audio_input(...) -> MessageResponse:
    # Read audio file
    audio_bytes = await audio_file.read()

    # Generate unique message ID early
    message_id = str(uuid.uuid4())

    # Store original audio (ephemeral, same TTL as translated audio)
    original_audio_url = f"/api/audio/input_{message_id}.wav"
    session_manager.store_original_audio(message_id, audio_bytes)

    # Process through pipeline
    result = process_wav(audio_bytes, source_lang, target_lang)

    # Transform debug to metadata
    pipeline_metadata = transform_debug_to_metadata(
        result.get("debug", {}),
        original_audio_url=original_audio_url,
        input_type="audio"
    )

    # Create message with metadata
    message = await create_session_message(
        session_id=session_id,
        client_type=client_type,
        original_text=result.get("asr_text", ""),
        translated_text=result.get("translation_text", ""),
        audio_bytes=result.get("audio_bytes"),
        source_lang=source_lang,
        target_lang=target_lang,
        manager=manager,
        pipeline_metadata=pipeline_metadata,  # ✅ NEW
        original_audio_url=original_audio_url  # ✅ NEW
    )
```

### 2. Timestamp Precision

**Challenge:** Pipeline steps execute sequentially, but we need exact timestamps.

**Solution 1 (Simple):** Record `time.perf_counter()` before/after each step

```python
# In pipeline_logic.py - process_wav()

start_total = time.perf_counter()
pipeline_start_time = datetime.now(timezone.utc)

# ASR
start_asr = time.perf_counter()
start_asr_absolute = datetime.now(timezone.utc)
# ... ASR processing ...
end_asr_absolute = datetime.now(timezone.utc)

debug_info["steps"].append({
    "step": "ASR",
    "input": {"lang": source_lang},
    "output": asr_text,
    "error": asr_json.get("error"),
    "duration": round(time.perf_counter() - start_asr, 3),
    "started_at": start_asr_absolute.isoformat(),    # ✅ NEW
    "completed_at": end_asr_absolute.isoformat()     # ✅ NEW
})
```

**Solution 2 (Alternative):** Calculate relative timestamps from durations

```python
# More accurate: Use perf_counter for precision, calculate absolute times
def calculate_step_timestamps(steps: List[Dict], pipeline_start: datetime):
    current_offset = 0
    for step in steps:
        step_duration = step["duration"]
        step["started_at"] = (pipeline_start + timedelta(seconds=current_offset)).isoformat()
        step["completed_at"] = (pipeline_start + timedelta(seconds=current_offset + step_duration)).isoformat()
        current_offset += step_duration
```

**Recommendation:** Use Solution 1 for maximum accuracy.

### 3. SessionMessage Enhancement

```python
# In session_manager.py

@dataclass
class SessionMessage:
    id: str
    sender: ClientType
    original_text: str
    translated_text: str
    audio_base64: Optional[str]
    source_lang: str
    target_lang: str
    timestamp: datetime

    # ✅ NEW FIELDS
    pipeline_metadata: Optional[Dict[str, Any]] = None
    original_audio_url: Optional[str] = None

    def to_dict(self):
        result = {
            "id": self.id,
            "sender": self.sender.value,
            "original_text": self.original_text,
            "translated_text": self.translated_text,
            "audio_base64": self.audio_base64,
            "source_lang": self.source_lang,
            "target_lang": self.target_lang,
            "timestamp": self.timestamp.isoformat(),
        }

        # ✅ Include metadata if present
        if self.pipeline_metadata is not None:
            result["pipeline_metadata"] = self.pipeline_metadata
        if self.original_audio_url is not None:
            result["original_audio_url"] = self.original_audio_url

        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionMessage":
        return cls(
            id=data["id"],
            sender=ClientType(data["sender"]),
            original_text=data.get("original_text", ""),
            translated_text=data.get("translated_text", ""),
            audio_base64=data.get("audio_base64"),
            source_lang=data.get("source_lang", ""),
            target_lang=data.get("target_lang", ""),
            timestamp=datetime.fromisoformat(data["timestamp"]),

            # ✅ Parse new fields
            pipeline_metadata=data.get("pipeline_metadata"),
            original_audio_url=data.get("original_audio_url")
        )
```

### 4. WebSocket Message Construction

```python
# In websocket.py - broadcast_with_differentiated_content()

# Receiver message (with translation + audio)
receiver_message = {
    "type": MessageType.MESSAGE.value,
    "message_id": message.id,
    "session_id": session_id,
    "text": message.translated_text,
    "source_lang": message.source_lang,
    "target_lang": message.target_lang,
    "sender": message.sender.value,
    "timestamp": message.timestamp.isoformat(),
    "audio_available": message.audio_base64 is not None,
    "audio_url": f"/api/audio/{message.id}.wav" if message.audio_base64 else None,
    "role": "receiver_message",
}

# ✅ Add metadata if available
if message.pipeline_metadata is not None:
    receiver_message["pipeline_metadata"] = message.pipeline_metadata

# Sender message (confirmation)
sender_message = {
    # ... same fields ...
    "role": "sender_confirmation",
}

# ✅ Optional: Include metadata in sender confirmation too
if message.pipeline_metadata is not None:
    sender_message["pipeline_metadata"] = message.pipeline_metadata
```

## Performance Considerations

### Message Size Impact

**Current WebSocket Message Size:** ~500 bytes

```json
{
  "type": "message",
  "role": "receiver_message",
  "message_id": "uuid-1234",
  "session_id": "ABC123",
  "text": "Hello, how can I help?",
  "sender": "admin",
  "timestamp": "2025-11-05T20:01:00Z",
  "audio_available": true,
  "audio_url": "/api/audio/uuid-1234.wav",
  "source_lang": "de",
  "target_lang": "en"
}
```

**With Metadata:** ~1.5-2KB (3-4x increase)

```json
{
  // ... existing fields (500 bytes) ...
  "pipeline_metadata": {
    "input": { ... },      // ~100 bytes
    "steps": [             // ~800-1000 bytes for 4 steps
      { ... },
      { ... },
      { ... },
      { ... }
    ],
    "total_duration_ms": 5000,
    "pipeline_started_at": "...",
    "pipeline_completed_at": "..."
  }
}
```

**Impact Analysis:**
- 100 concurrent sessions × 2KB/message × 10 messages/minute = 20KB/min = 1.2MB/hour
- **Negligible** for modern networks
- If needed: Add toggle to disable metadata in high-load scenarios

### Serialization Overhead

**Current:** `json.dumps(message)` → ~0.1ms
**With Metadata:** `json.dumps(message_with_metadata)` → ~0.15ms
**Increase:** ~50% but still negligible (<1ms)

### Memory Impact

**Original Audio Storage:**
- 10-second audio @ 16kHz = ~320KB
- 100 concurrent sessions = 32MB
- Need cleanup mechanism (already exists for translated audio)

## Error Handling

### What if Pipeline Step Fails?

```python
# In pipeline_logic.py

try:
    translation_resp = requests.post(TRANSLATION_URL, ...)
    translation_json = translation_resp.json()
    # ... success path ...
except Exception as e:
    debug_info["steps"].append({
        "step": "Translation",
        "input": translation_payload,
        "output": None,
        "error": str(e),                           # ✅ Error captured
        "duration": round(time.perf_counter() - start_trans, 3),
        "started_at": start_trans_time.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat()
    })
```

Frontend can then check:

```typescript
if (msg.pipeline_metadata?.steps.some(s => s.error)) {
  console.error("Pipeline had errors:",
    msg.pipeline_metadata.steps.filter(s => s.error)
  );
}
```

## Security Considerations

### Original Audio URLs

**Risk:** Original audio URLs could expose sensitive conversations

**Mitigation:**
1. Same authorization as translated audio (session-based)
2. Ephemeral URLs (expire with session)
3. No permanent storage
4. Same access control: only participants in session

### Metadata Information Disclosure

**Risk:** Metadata could reveal backend architecture (model names, service URLs)

**Mitigation:**
1. Filter sensitive fields before sending (internal IPs, full stack traces)
2. Expose only: model names, durations, step names
3. Don't include: service URLs, internal errors, infrastructure details

```python
# Safe metadata exposure
{
  "name": "translation",
  "output": {
    "text": "...",
    "model": "m2m100_1.2B"  # ✅ Safe to expose
  }
}

# Unsafe (don't include)
{
  "name": "translation",
  "output": {
    "text": "...",
    "service_url": "http://translation:8000",  # ❌ Internal infrastructure
    "stack_trace": "..."                        # ❌ Internal error details
  }
}
```

## Testing Strategy

### Unit Tests

```python
def test_transform_debug_to_metadata():
    debug_info = {
        "steps": [
            {"step": "ASR", "duration": 2.5, "output": "Hello"},
            {"step": "Translation", "duration": 0.5, "output": "Hallo"}
        ],
        "total_duration": 3.0
    }

    metadata = transform_debug_to_metadata(debug_info, input_type="audio")

    assert metadata["input"]["type"] == "audio"
    assert len(metadata["steps"]) == 2
    assert metadata["steps"][0]["name"] == "asr"
    assert metadata["steps"][0]["duration_ms"] == 2500
    assert "started_at" in metadata["steps"][0]
    assert "completed_at" in metadata["steps"][0]
```

### Integration Tests

```python
async def test_websocket_message_includes_metadata():
    # Send audio message
    response = await client.post(
        f"/api/session/{session_id}/message",
        files={"audio": ("test.wav", audio_bytes)}
    )

    # Wait for WebSocket message
    ws_message = await ws.receive_json()

    # Validate metadata
    assert "pipeline_metadata" in ws_message
    assert ws_message["pipeline_metadata"]["input"]["type"] == "audio"
    assert len(ws_message["pipeline_metadata"]["steps"]) >= 3  # ASR, Translation, TTS
    assert ws_message["pipeline_metadata"]["total_duration_ms"] > 0
```

### E2E Tests

Extend `test_end_to_end_conversation.py`:

```python
def validate_translation(self, step: Dict[str, Any], ws_data: Dict[str, Any]):
    # ... existing validation ...

    # ✅ Validate metadata
    if "pipeline_metadata" in ws_data:
        metadata = ws_data["pipeline_metadata"]

        assert "steps" in metadata, "Missing steps in metadata"
        assert "total_duration_ms" in metadata

        # Validate step names
        step_names = [s["name"] for s in metadata["steps"]]
        if step["audio_file"]:
            assert "asr" in step_names
        assert "translation" in step_names
        assert "tts" in step_names

        # Validate timestamps
        for step in metadata["steps"]:
            assert "started_at" in step
            assert "completed_at" in step
            assert datetime.fromisoformat(step["started_at"])  # Valid ISO
```

## Rollback Plan

If issues arise in production:

1. **Toggle Off Metadata:** Set `ENABLE_PIPELINE_METADATA=false` → metadata not included in messages
2. **Keep Backend Changes:** SessionMessage can still have metadata field (just not sent)
3. **Frontend Ignores:** Old/new frontend both work (metadata is optional)

No data loss, no breaking changes.

## Future Enhancements

### Phase 2 Ideas (Not in Scope)

1. **Compression:** Gzip metadata for large messages
2. **Selective Metadata:** WebSocket param `?metadata_fields=steps,total_duration`
3. **Streaming Updates:** Send step-by-step updates as pipeline progresses
4. **Model Performance Tracking:** Aggregate metadata for analytics
5. **Error Attribution:** Better debugging when specific service fails

## Summary

This design ensures:
- ✅ **100% Backward Compatible:** Metadata is optional
- ✅ **Minimal Overhead:** <1ms serialization, <2KB per message
- ✅ **Clean Architecture:** Transform existing debug_info to metadata format
- ✅ **Testable:** Clear unit/integration/E2E test strategy
- ✅ **Secure:** No sensitive infrastructure details exposed
- ✅ **Flexible:** Frontend decides what to do with metadata
