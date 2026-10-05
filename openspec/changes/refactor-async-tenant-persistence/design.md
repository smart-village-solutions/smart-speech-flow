# Design: non-blocking tenant persistence

## Decision: `redis.asyncio` for both stores, not a thread-pool adapter

The issue offered an interim adapter that runs the synchronous calls through
`asyncio.to_thread`. It saves only the Redis adapters' bodies: every manager
method that reaches the store still has to become a coroutine, so the ripple
through routes, transports and tests is the same. It would also put each Redis
round trip into the default thread pool, which under load is a second
bottleneck, and leave a second migration for later. Both stores therefore move
to `redis.asyncio` now, on the one connection `configure_tenant_persistence()`
verifies. The ticket store moves with the session store because they share it.

## Decision: the ports are async; the memory adapters never await

`TenantSessionStore` and `RealtimeTicketBackend` declare coroutines. The memory
adapters implement them as `async def` bodies with no `await`, so each call is
still atomic with respect to the loop, which the tests that race them rely on.

## Decision: per-session write ordering in the Redis store

Once a save awaits, two handlers that change one session can interleave, and
their two `EVAL`s can reach Redis on different pool connections in either
order. If the older snapshot landed last, Redis would hold a session that
regressed: an earlier status, fewer messages, a stale connection count — and
the active-session listing, which reads the store, would show it.

The Redis store therefore holds one `asyncio.Lock` per session key around
`create`, `save` and `terminate`, and builds the payload inside the lock. Every
write then stores the session's state at the moment it runs, which is never
older than the write before it. `asyncio.Lock` is fair, so writes also apply in
the order they were issued. The lock map drops a key once no writer holds or
awaits it, so it stays bounded by the sessions being written at that moment.

A termination that commits between two saves still makes the later save fail
with `SessionStoreConsistencyError`, as a save after termination does today.

## Decision: one session object per key

`get_session` fills the cache on a miss. Two handlers that miss concurrently
would each load their own `Session` and the second would replace the first in
the cache, leaving one handler mutating an object nobody saves again. After the
load returns, `get_session` keeps whichever object is already cached and
discards its own.

## Decision: the content sweep tolerates concurrent appends

The sweep prunes the live session and then saves it. While that save awaits,
`add_message` can append to the same list. If the save fails, the sweep
restores the pruned messages together with anything appended meanwhile,
instead of restoring the list it captured before the await. Refused audio is
still deleted only once the pruned record has committed. The sweep now yields
between sessions, so the hourly pass no longer holds the loop.

## Decision: a load reads its record and join as one snapshot

`load` used to read the session record and its join with two `GET`s. With a
synchronous client nothing could run between them; once they await, a
termination can commit in between, and the load would see an active record
beside a revoked join, quarantine it in the log and answer 404 to a request
that arrived while the session was still live. It now reads both with one
`MGET`, which Redis serves atomically, and saves a round trip.

## Decision: a pruned polling batch is released in full

The polling routes prune idle pollers and release their presence as one batch,
which the synchronous code did without a cancellation point. Each release now
awaits a session save, so a request cancelled part-way would leave the
remaining sessions counting pollers that no longer exist. The batch runs as its
own task, shielded from the request's cancellation and referenced by the
polling store until it finishes.

## Decision: work that used to run without a yield is serialized explicitly

Review of the first cut found three more places where a synchronous sequence
had been atomic only because nothing could interleave with it:

- **Session creation.** Ending an admin's previous session and creating the
  next listed the tenant's sessions and then created one. Two concurrent
  creates by one admin now both await the listing, and both would find nothing
  to end. Creation holds a lock per tenant and owner.
- **Termination.** Two terminations of one session could both pass the
  status check; the second committed through the store's idempotent path and
  reported the termination a second time. A termination that finds the cached
  session already terminated once its own commit returns stops there.
- **Polling activation.** A termination while the activation awaits misses a
  poller not yet registered. The activation withdraws the poller and answers
  404 when the session has ended by the time its presence is recorded.

A failed sweep write no longer rolls back onto a session a concurrent
termination replaced, and keeps an authorization recorded on a message while
it awaited. A tenant listing reads every record and join in one `MGET`.
Shutdown waits for pending presence releases before closing the connection,
and a failed startup closes it.

## Decision: the access guards run on the loop

`require_admin_session_key` and `require_customer_session_key` become `async`
dependencies. They stop using the thread pool, and stop touching the session
cache from a worker thread while handlers on the loop change it.

## Compatibility

Keys, Lua scripts and serialized values are unchanged, so records written by
the previous release load in this one and vice versa. `decode_responses`, the
5-second connect and socket timeouts and the startup `PING` are kept.
