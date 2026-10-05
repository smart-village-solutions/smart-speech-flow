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

## Decision: a change that waited behind a termination fails

A save can queue behind a termination of the same session. The termination
then copies the terminal record onto the cached session the save is about to
serialize, so the save sends that record unchanged, and the save script accepts
an unchanged terminal record as a no-op. The store reports success; the change
the caller made — a new connection, an activation, a message — is gone.

The store cannot tell this save from a legitimate idempotent one, but the
manager can: after the save it checks the session's status, and if a
termination committed meanwhile it raises what the method raises for a
session that had already ended — `KeyError` for a connection, `ValueError`
for an activation, `SessionStoreConsistencyError` for a message or an
authorization. A guest socket connecting behind a termination is therefore
closed with 4404 instead of joining the live set after the termination
broadcast. Disconnections and the timeout warning keep the plain save: on an
ended session they have nothing left to change.

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

## Decision: a bounded, blocking connection pool

`redis.asyncio`'s default pool allows 100 connections and raises
`MaxConnectionsError` as soon as all are in use; the synchronous pool it
replaces had no practical limit, and no more callers than the thread pool's
workers. A stalled Redis with more than 100 commands in flight would turn
ticket operations into 503s and fail session saves. The client therefore
uses a `BlockingConnectionPool` of the same 100 connections, on which a
command waits for a free connection for up to 5 seconds — the socket
timeout — so a burst queues instead of failing, and a stalled Redis fails a
waiting command no later than a running one.

## Decision: the polling lock holds no Redis round trip

The polling store's mutation lock covers every tenant. Holding it across a
Redis round trip would let one slow save stall polling everywhere. Under the
lock the routes now only prune, register and start the pruned batch's release;
they consume the realtime ticket, look the session up and await the release
outside it. Releasing after the lock is released is safe: the pruned clients
are already out of the store, and presence counts move the same way whichever
order a release and a new connection apply in. One failed release no longer
stops its batch, and a release a cancelled request no longer awaits logs its
failure instead of losing it.

## Accepted edge cases

- If a sweep save fails after Redis committed it, the cache rolls back while
  Redis keeps the pruned record. The next save of that session writes the
  unpruned content back, and the next hourly sweep prunes it again.
- The timeout monitor prunes idle pollers without a shielded release, as it
  did before this change. It is cancelled only at shutdown, and startup
  rehydrate resets presence.
- Two admins of one tenant creating sessions at the same moment can each read
  the tenant's list before the other's session exists. Only their own
  sessions count for each of them, so neither ends the other's.

## Decision: the access guards run on the loop

`require_admin_session_key` and `require_customer_session_key` become `async`
dependencies. They stop using the thread pool, and stop touching the session
cache from a worker thread while handlers on the loop change it.

## Compatibility

Keys, Lua scripts and serialized values are unchanged, so records written by
the previous release load in this one and vice versa. `decode_responses`, the
5-second connect and socket timeouts and the startup `PING` are kept.
