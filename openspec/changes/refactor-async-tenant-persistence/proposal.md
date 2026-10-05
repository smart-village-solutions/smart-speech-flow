# Change: Make the gateway's tenant persistence non-blocking

## Why

Issue #428, task 2.2b of `refactor-api-gateway-boundaries` (#228). The tenant
session store and the realtime ticket store call Redis with the synchronous
client from async request and WebSocket handlers. Every session read and write
blocks the event loop for one Redis round trip, and the hourly content sweep
blocks it for the whole pass. The session access guards avoid the loop only
because FastAPI runs synchronous dependencies in its thread pool, where they
share the session cache with handlers on the loop.

## What Changes

- The `TenantSessionStore` and `RealtimeTicketBackend` ports become async. The
  Redis adapters move to `redis.asyncio` on one shared connection, with the
  same Lua scripts and key layout; the memory adapters keep their semantics.
- `configure_tenant_persistence()` builds and verifies an async client, and
  the lifespan closes it.
- `TenantSessionManager` methods that reach the store become coroutines, and
  every caller awaits them: the access guards, REST routes, WebSocket and
  polling transports, message delivery, feedback resolution, the lifespan
  rehydrate and the retention sweep.
- Writes to one session apply in the order they were issued, and a cache miss
  that resolves concurrently yields one shared session object.
- A guard test forbids the synchronous Redis client in production gateway
  modules, and real-Redis tests cover the async session store.

No public REST, WebSocket, polling or OpenAPI behaviour changes, and the Redis
keys and values stay byte-compatible, so a rolling restart needs no migration.

## Impact

- Affected specs: `api-gateway-modular-architecture`.
- Affected code: `services/api_gateway` (session_store, realtime_ticket,
  tenant_persistence, session_manager, session_access, websocket,
  websocket_polling_routes, message_delivery, message_processing,
  conversation_service, session_lifecycle, routes/admin, routes/customer,
  feedback/service, background_tasks, app); the gateway tests.
- Out of scope: `tenant_cutover.py`, an offline CLI, and the test-only
  `LegacySessionManager` keep the synchronous client.
