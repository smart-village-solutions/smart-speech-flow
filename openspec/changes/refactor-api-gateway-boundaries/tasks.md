## 1. Baseline and Contracts

- [ ] 1.1 Capture REST/OpenAPI, WebSocket-frame, polling, and Redis-session characterization fixtures for existing behavior.
- [ ] 1.2 Document ownership and dependency rules for the new gateway layers.
- [ ] 1.3 Add typed configuration and a lifespan-owned dependency container without changing public behavior.

## 2. Domain and Persistence

- [ ] 2.1 Move session, message, status, language-policy, and domain-event types into the domain layer.
- [ ] 2.2 Define asynchronous `SessionRepository` and implement memory and Redis adapters with legacy-data compatibility.
- [ ] 2.3 Implement `SessionService` and migrate admin/customer/session lifecycle routes.
- [ ] 2.4 Add repository parity, lifecycle, timeout, and Redis migration tests.

## 3. Speech Pipeline and Messaging

- [ ] 3.1 Define the `SpeechPipeline` port and typed processing-result contract.
- [ ] 3.2 Extract audio validation, conversion/storage, and ASR/Translation/TTS HTTP clients into infrastructure adapters.
- [ ] 3.3 Implement `MessageService` and migrate unified text/audio message handling and pipeline metadata creation.
- [ ] 3.4 Add unit and integration coverage for validation, service failures, metadata, and message persistence.

## 4. Realtime and Runtime

- [ ] 4.1 Define realtime protocol models and extract connection registry, dispatcher, and heartbeat components.
- [ ] 4.2 Extract polling fallback, adaptive polling, and realtime monitoring behind focused interfaces.
- [ ] 4.3 Migrate WebSocket, polling, and monitoring routes while preserving frame and endpoint contracts.
- [ ] 4.4 Move background loops into `runtime/tasks.py` and verify graceful startup and shutdown.
- [ ] 4.5 Add WebSocket lifecycle, broadcast, heartbeat, fallback, and monitoring integration tests.

## 5. Cleanup and Verification

- [ ] 5.1 Migrate all first-party production imports and tests to the new packages.
- [ ] 5.2 Convert legacy gateway modules into temporary compatibility facades and prohibit new production imports.
- [ ] 5.3 Remove the unregistered duplicate `services/api_gateway/session.py` after consumer verification.
- [ ] 5.4 Run the complete backend suite, API/OpenAPI contract tests, realtime integration tests, and load smoke tests.
- [ ] 5.5 Update architecture and operational documentation with the final dependency map and migration status.
