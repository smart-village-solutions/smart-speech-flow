# Change: Retire legacy gateway paths and consolidate duplicate processing

## Why

Issue #230. The gateway still serves unauthenticated, tenant-less legacy routes
(`POST /pipeline`, `POST /upload`, `GET /`) that no first-party client calls. The
audio and text pipelines implement their translation, refinement and TTS tail
twice and have drifted. There is no policy for unhandled errors, so broad
exception handlers reshape errors locally. Five gateway modules exceed 950
lines. The default Compose build references `../ssf-frontend`, which a clone of
this repository does not contain.

## What Changes

- Remove `frontend-archive` from development Compose, and guard every default
  build context to stay inside the repository.
- **BREAKING:** remove `POST /pipeline`, `POST /upload` and `GET /`, together
  with their legacy-only audio-validation branch, and the `logging.basicConfig`
  calls at import time.
- Run audio and text messages through one translation → refinement → TTS tail.
- **BREAKING:** a completely empty ASR transcript answers 422
  `NO_SPEECH_RECOGNIZED`, and the frontend tells the speaker.
- Add one unhandled-error middleware. Remove broad exception handlers that
  only reshape errors, narrow the rest, and inventory every remaining broad
  handler in a guard test.
- ASR errors and a missing ASR model answer 500 instead of a fabricated
  transcript. TTS rejects a request without text.
- Split the oversized gateway modules under an 800-line budget.

## Impact

- Affected specs: `api-gateway-modular-architecture`, `local-development` (new).
- Affected code: `docker-compose.yml`; `services/api_gateway` (routes,
  pipeline_logic, message_processing, app, session_manager, quality_telemetry,
  websocket); `services/asr`, `services/translation` and `services/tts` error
  handling; the frontend `core/http` layer; tests and docs.
- Delivered as five PRs that reference #230. Only the last one closes it.
- Out of scope:
  - a single error envelope (#226)
  - packaging (#225, #229)
  - WebSocket monitoring (#348)
  - the wider documentation rewrite (#231)
