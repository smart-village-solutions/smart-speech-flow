## 1. Characterization and Composition Root

- [x] 1.1 Characterize current tenant-scoped admin/customer REST, Studio-runtime failure, consent/persistence, pipeline-metadata, realtime-ticket, polling, and lifespan contracts.
- [x] 1.2 Define dependency ownership and no-new-global rules, including provider override patterns for tests.
- [x] 1.3 Introduce a lifespan-owned `GatewayDependencies` container and dependency providers without changing public behavior.
- [x] 1.4 Migrate existing app-state collaborators and global adapters incrementally; add tests that isolated app instances do not share injected dependencies.
  - `session_manager`, the runtime policy gate, `circuit_breaker_client`, `service_health_manager`, `graceful_degradation_manager`, `fallback_manager`, `translation_refiner`, the WebSocket monitor, the Prometheus registry and metric objects, and `auth._key_cache` remain adapters; design.md names the PR that removes each.
  - #347 §4's "`tenant_persistence.py` no longer reassigns module globals" is complete for the ticket store. For the session store it completes in PR4.

## 2. Session, Message, and Pipeline Boundaries

- [ ] 2.1 Record the legacy session cutover decision and operational evidence; either plan deletion or define a typed compatibility adapter.
- [ ] 2.2 Define tenant-aware session/message domain contracts and async persistence ports while retaining `TenantSessionKey`, join-index, Redis, consent, and runtime-snapshot semantics.
- [ ] 2.3 Extract application services for session lifecycle and message processing; migrate routes without public contract drift.
- [ ] 2.4 Extract speech HTTP, validation/conversion, and audio-storage adapters behind typed ports; preserve pipeline metadata and failure mapping.
- [ ] 2.5 Add parity, lifecycle, cross-tenant, persistence, and pipeline contract coverage.

## 3. Realtime, Polling, and Monitoring Boundaries

- [ ] 3.1 Define typed realtime protocol and ticket-backend operations; migrate memory and Redis implementations without exposing Lua details.
- [ ] 3.2 Extract connection registry, dispatcher, heartbeat, polling fallback, and monitoring collaborators behind focused interfaces.
- [ ] 3.3 Migrate WebSocket, polling, and supported monitoring routes while preserving tenant isolation, frame, and endpoint behavior.
- [ ] 3.4 Add realtime lifecycle, broadcast, heartbeat, polling, and cross-tenant denial integration coverage; coordinate public monitoring scope with #348.

## 4. Compatibility Cleanup and Verification

- [ ] 4.1 Migrate first-party production imports and tests to the new boundaries; prohibit new production imports of compatibility adapters.
- [ ] 4.2 Inventory remaining facades and consumers; remove only adapters with no required consumers.
- [ ] 4.3 Remove obsolete duplicate modules only after consumer search and compatibility proof.
- [ ] 4.4 Run the full gateway contract suite, tenant-isolation matrix, realtime integration suite, and configured real-system smoke coverage.
- [ ] 4.5 Update architecture and operations documentation with final dependency ownership and migration status.

## 5. Consistency Items from #347

- [x] 5.1 Record audio availability on the message when it is written; listing messages performs no filesystem stat per message (#347 §6).
- [x] 5.2 Compare the Studio tenant id in constant time, matching the adjacent authorization-revision check in studio_runtime_flow.py (#347 §6).
- [x] 5.3 Normalise tenant selector names (casefold, strip "_" and "-") instead of enumerating spellings in tenant_context.py (#347 §6).
