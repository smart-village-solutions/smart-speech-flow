# Change: Refactor API Gateway Boundaries

## Why

The API gateway combines HTTP and WebSocket transport, session lifecycle, Redis persistence, speech-pipeline orchestration, audio processing, polling fallback, monitoring, and runtime scheduling in a small number of highly coupled modules. This makes behavior difficult to test in isolation and causes routine changes to cross unrelated responsibilities.

## What Changes

- Introduce a layered gateway architecture with explicit domain, application, port, infrastructure, realtime, presentation, and runtime boundaries.
- Replace direct coupling among route handlers, `SessionManager`, `WebSocketManager`, and pipeline functions with typed application services and dependency-injected ports.
- Separate session persistence, speech-service clients, audio processing, realtime connection handling, polling fallback, and background tasks into dedicated components.
- Preserve all current public REST, WebSocket, polling, OpenAPI, and message-metadata contracts.
- Retain temporary compatibility import facades while first-party consumers migrate, then remove obsolete duplicate and facade modules in a later cleanup step.

## Impact

- Affected capability: `api-gateway-modular-architecture`
- Affected code: `services/api_gateway`, gateway tests, architecture documentation
- Compatibility: no intentional change to public APIs, WebSocket frame types, Redis session data, or deployment topology
- Coordination: this change overlaps with active quality work in gateway files. Implementations must be sequenced after, or rebased onto, relevant quality fixes; no competing edits to the same production file should be merged concurrently.

## Non-Goals

- Redesigning ASR, Translation, or TTS service internals
- Introducing a message broker or changing the single-gateway-replica realtime deployment model
- Changing authentication, authorization, rate limits, session rules, or public endpoint behavior
- Replacing Redis as the existing session persistence backend
