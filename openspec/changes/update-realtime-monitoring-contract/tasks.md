## 1. Implementation

- [x] 1.1 Remove `WebSocketMonitor.get_connection_stats()` and the connection history only it read, and the unused `_performance_samples` and `_extract_domain`.
- [x] 1.2 Remove the legacy `tests/integration/test_websocket_integration.py` and its references.
- [x] 1.3 Document the monitoring contract: endpoints, authorization, scope and response fields.

## 2. Verification

- [x] 2.1 Contract tests for the monitoring route table, the aggregate-only health payload, and permitted and cross-tenant session connection listing, each proven to fail against a reintroduced leak.
- [x] 2.2 Full CI pytest subset, format and type gates; the same suite on a merge with `origin/main`.
- [x] 2.3 OpenAPI snapshot unchanged.
