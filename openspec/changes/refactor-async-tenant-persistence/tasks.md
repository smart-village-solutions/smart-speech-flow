## 1. Ports and adapters
- [x] 1.1 Async `RealtimeTicketBackend`, ticket store and both adapters
- [x] 1.2 Async `TenantSessionStore`, memory adapter and `redis.asyncio` adapter with per-session write ordering
- [x] 1.3 `configure_tenant_persistence()` builds, verifies and closes an async client

## 2. Manager and callers
- [x] 2.1 `TenantSessionManager` store-touching methods become coroutines; single-flight cache fill
- [x] 2.2 Content sweep awaits each save and tolerates concurrent appends
- [x] 2.3 Access guards, routes, WebSocket, polling, message delivery, feedback, lifespan and retention pass await the manager
- [x] 2.4 `load` reads record and join in one `MGET`; a pruned polling batch is released in full despite cancellation
- [x] 2.5 Per-owner creation lock, single termination report, polling activation withdrawn on termination, batched tenant listing, shutdown drains presence releases, failed startup closes the client
- [x] 2.6 A change that waited behind a termination fails as on an ended session; blocking connection pool; polling lock holds no Redis round trip; batch releases survive one failure and log

## 3. Evidence
- [x] 3.1 Guard: no synchronous Redis client in production gateway modules, watched failing
- [x] 3.2 Hermetic tests for write ordering, single-flight load, the sweep's concurrent append, the snapshot load and the cancelled polling batch, each watched failing
- [x] 3.3 Real-Redis tests for the async session store; ticket Redis tests on the async client
- [x] 3.4 Gateway contract suite and tenant isolation matrix green; full CI gates green merged with `origin/main`
