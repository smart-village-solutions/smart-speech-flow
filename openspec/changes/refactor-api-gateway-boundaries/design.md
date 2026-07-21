## Context

The gateway currently has several broad modules: `routes/session.py` mixes request handling with session and pipeline behavior; `session_manager.py` owns domain objects, persistence, lifecycle, connection state, and singleton setup; `pipeline_logic.py` combines validation, audio conversion, orchestration, and HTTP calls; and `websocket.py` combines protocol, registry, dispatch, heartbeat, fallback, monitoring, and routes. `app.py` also owns configuration, dependency initialization, and all background tasks.

Public clients depend on the existing REST and WebSocket contracts. Existing Redis data and the active in-process realtime registry must remain usable throughout the migration.

## Goals / Non-Goals

### Goals

- Make each gateway responsibility independently testable and replaceable.
- Establish one dependency direction: presentation -> application -> domain/ports, with infrastructure and realtime implementing ports.
- Construct concrete dependencies once during FastAPI lifespan and expose them through dependency providers.
- Preserve endpoint paths, request and response schemas, WebSocket frames, polling behavior, and persisted session format.

### Non-Goals

- Add distributed WebSocket dispatch or multi-replica synchronization.
- Modify external AI-service interfaces.
- Alter the product's session lifecycle or language policies.

## Decisions

### Decision: Layered package boundaries

The target gateway package structure is:

```text
services/api_gateway/
  app.py                    # composition root only
  config.py                 # typed runtime configuration
  domain/                   # sessions, languages, domain events
  application/              # session, message, and conversation services
  ports/                    # repository, speech pipeline, realtime publisher protocols
  infrastructure/           # Redis/memory repositories, HTTP clients, audio adapters
  realtime/                 # protocol, registry, dispatcher, heartbeat, polling, monitoring
  presentation/             # HTTP and WebSocket route adapters
  runtime/                  # periodic tasks and shutdown management
  compatibility/            # temporary legacy import facades
```

Dependencies must point inward. Domain code must not import FastAPI, Redis, HTTP clients, WebSockets, or Prometheus. Presentation code must not mutate persisted session objects directly.

### Decision: Typed ports and results

The application layer depends on `SessionRepository`, `SpeechPipeline`, and `RealtimePublisher` protocols. The speech pipeline returns a typed processing result, and realtime delivery returns a typed broadcast result. Raw dictionaries remain only at transport boundaries and are converted by presentation or adapter code.

### Decision: Session persistence is a repository concern

`MemorySessionRepository` and `RedisSessionRepository` implement the same asynchronous repository port. Redis setup, serialization, loading, persistence failure handling, and fallback behavior move out of session lifecycle code. The serialized `Session` and `SessionMessage` representation remains compatible with existing Redis entries.

### Decision: Session and message workflows are application services

`SessionService` owns create, activate, terminate, activity update, and timeout workflows. `MessageService` owns input validation, language-pair enforcement, speech-pipeline invocation, message persistence, and publication of a domain event. `ConversationService` supplies session state and message history. Route handlers map HTTP requests and errors to these services but do not contain business decisions.

### Decision: Realtime consists of focused collaborators

The realtime package separates:

- `protocol`: Pydantic models and message-type translation.
- `connection_registry`: in-process connection ownership by session and participant type.
- `dispatcher`: targeted delivery and broadcast accounting.
- `heartbeat`: ping/pong state and connection expiry.
- `polling`: adaptive intervals plus WebSocket fallback integration.
- `monitoring`: metrics and diagnostics.

The WebSocket route performs origin and parameter validation, creates or resolves a connection, receives frames, delegates handling, and translates failures. Session application services notify realtime only through `RealtimePublisher`; neither side imports the other's manager implementation.

### Decision: Dependency injection replaces global runtime ownership

`app.py` builds adapters and application services during lifespan, stores the composed service container in application state, and starts runtime tasks from `runtime/tasks.py`. FastAPI dependency providers retrieve those instances. There must be no lazy global manager initialization in new code.

### Decision: Incremental compatibility migration

Existing public APIs remain stable. The old `session_manager.py`, `pipeline_logic.py`, and `websocket.py` paths become documented compatibility facades only after their first-party callers have moved. Tests move with the owned component. The unregistered duplicate `services/api_gateway/session.py` is removed only after a repository-wide consumer search confirms it has no required import path.

## Risks / Trade-offs

- Moving boundaries can introduce subtle response or WebSocket-frame drift.
  - Mitigation: characterize current public behavior first and run API/OpenAPI and realtime integration tests after every migration slice.
- Redis serialization changes could make active sessions unreadable.
  - Mitigation: retain keys and wire shape, add fixtures for legacy data, and test read/write parity across both repositories.
- In-process realtime dispatch remains limited to one gateway process.
  - Mitigation: retain an explicit `RealtimePublisher` port so a Redis Pub/Sub implementation can be added without changing domain or route code.
- Compatibility facades can become permanent debt.
  - Mitigation: define their removal as an explicit final task and reject new production imports of them.

## Migration Plan

1. Add domain types, ports, configuration, and characterization tests without changing route behavior.
2. Move persistence behind repositories and migrate session lifecycle to `SessionService`.
3. Split speech pipeline adapters and migrate message processing to `MessageService`.
4. Extract realtime collaborators and migrate REST/WebSocket/polling routes.
5. Centralize lifespan composition and periodic tasks.
6. Migrate all first-party imports and tests, remove the duplicate legacy module, then retire compatibility facades in a follow-up cleanup release.

## Rollback Plan

Each migration slice is independently releasable and preserves public and Redis contracts. If a slice regresses, revert that slice while retaining its characterization tests; the preceding facade-backed implementation remains available.
