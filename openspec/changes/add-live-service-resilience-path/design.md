## Context

`process_wav` and `process_text_pipeline` are synchronous. Since #189 the routes
call them through `run_pipeline`, which puts them on a worker thread via
`asyncio.to_thread` and bounds how many run at once (#191). That design is
load-bearing: `PipelineAdmission` releases its slot from inside the worker
thread precisely because the call is uninterruptible, and `_SlotClaim` exists to
settle which of two threads returns the slot.

So the resilience path has to be reachable from a thread with no running event
loop, without making the pipeline async.

## Goals / Non-Goals

- Goal: every production ASR, translation and TTS call consults a breaker and
  reports its outcome to it.
- Goal: `/circuit-breaker/*` reflects live request traffic, not just health polls.
- Goal: no fabricated result can reach a user.
- Goal: the pipeline's existing failure classification, 503 handling,
  `debug["steps"]` trail and per-stage timeouts survive unchanged.
- Non-Goal: making the pipeline async. That reopens `PipelineAdmission` and
  every route, and is the composition-root work in #228.
- Non-Goal: real degradation behaviour (returning a transcript when TTS is
  down). That is a product decision and belongs to Philipp, not to this change.
- Non-Goal: bounding the Ollama refinement call.

## Decisions

### One state machine, two front doors

`CircuitBreaker` gets a synchronous API beside the async one:

```python
with breaker.guard():          # raises CircuitBreakerOpenError when OPEN
    ...                        # caller does the work
breaker.record_success(elapsed)
breaker.record_failure(reason)
```

The state transitions move into private synchronous methods guarded by a
`threading.Lock`; `async call()` and the sync API both drive those. Nothing
inside the transitions awaits — the only `await` in the current code is
`_notify_state_change`, which is dispatched after the lock is released.

Alternative considered: a dedicated event-loop thread and
`run_coroutine_threadsafe` into the existing async client. Rejected because the
async client's URLs, payloads, timeouts and return shapes would all have to be
rewritten to match the pipeline first (see the proposal), and because an
`aiohttp.ClientSession` is bound to the loop that created it — pinning one to a
side loop for the life of the process is a second lifecycle to get wrong.

Alternative considered: making the pipeline async end to end. Rejected as #228.

### Notification across threads

`on_state_change` is an async callback (`ServiceHealthManager._on_circuit_state_change`),
and it only logs. When a transition happens on a worker thread, the breaker
dispatches it with `asyncio.run_coroutine_threadsafe` onto the loop it was bound
to at monitoring start, and falls back to logging the transition directly when
no loop is running. A lost log line must never cost a state transition.

### What counts as a failure

| Outcome | Breaker | Rationale |
|---|---|---|
| `requests` transport error, timeout | failure | the service did not answer |
| 5xx | failure | the service answered wrongly |
| `503` **with** `Retry-After` | **not** a failure | #190 shedding by a working service; the client already has its retry signal, and breaking here turns a queue into an outage |
| 4xx | not a failure | the service is healthy and rejecting a bad request |
| 2xx | success | — |

A `503` with no parseable `Retry-After` is treated as an ordinary 5xx.

### Timeouts stay where they are

`CircuitBreakerConfig.timeout` is set by `register_service` from the *health
endpoint* budget — 10s for ASR, 8s for translation, 10s for TTS. The sync path
does not apply it. The per-call `requests` timeouts (60s / 30s / 45s) remain the
only bound on a real inference call.

### An open breaker is an ordinary pipeline failure

`call_ai_service` raises `CircuitBreakerOpenError`. `process_wav` and
`process_text_pipeline` catch it per stage and return `_pipeline_error_result`
with `failed_stage` set, `error_code: upstream_circuit_open`, and a `503` whose
`Retry-After` comes from `CircuitBreaker._time_until_next_attempt()`. This is
the same envelope the routes already turn into a 503 for `SYSTEM_BUSY`, so no
route or client changes.

## Risks / Trade-offs

- **Shared breaker state across tests.** The breakers are process-wide
  singletons from `CircuitBreakerFactory`. A test that drives three failures
  would leave a breaker OPEN for the next test. Mitigated by a single autouse
  fixture in a **root** `conftest.py`, added before the call sites move. The
  root is the point: `tests/conftest.py` cannot reach `services/*/tests/`, and
  both trees touch the same singletons. It resets each circuit individually
  rather than calling `reset_all()`, because `reset()` deliberately keeps the
  lifetime counters an operator wants, so the `ServiceHealth` record is
  replaced too -- along with the bound notification loop, which a closed loop
  would otherwise leave silently swallowing transitions.
- **`requests` stays the transport**, so the issue's literal "asynchronous
  service-client path" is not met. What is met is one path, used by everything,
  with live breaking. Recorded here rather than hidden.
- **The health poll reports failures to the breaker but never successes.**
  Sharing a breaker between the poll and real traffic is only safe in one
  direction. A failed ping is evidence: a service that cannot answer
  `/health` cannot serve inference, so it opens the breaker without waiting
  for three users to hit the failure. A *successful* ping is not evidence of
  anything the pipeline cares about, and letting it count toward
  `success_threshold` reclosed a breaker the pipeline had opened — measured at
  roughly every 75s, indefinitely, with no inference request ever succeeding.
  The exponential backoff could not accumulate either, because
  `_open_circuit` multiplies the timeout only on a HALF_OPEN → OPEN
  transition while `_close_circuit` resets it. Only a served request closes a
  breaker now.

  The cost is accepted deliberately: after an outage on an idle system the
  breaker stays OPEN and `/api/health/degradation` reports `degraded` until
  real traffic verifies recovery. `/api/health/services` still shows the
  service reachable, because the ping still runs while the circuit is open.
  Two separate facts, both reported.
- **A half-open breaker is not full service.** The degradation mode is
  derived from breakers being CLOSED, not merely not-OPEN. A half-open
  breaker will admit a probe but has not been shown to work, and counting it
  as usable made the mode flap to `full` during every recovery cycle of a
  genuine outage.
- **A half-open breaker admits one request at a time.** `_admit` gates
  HALF_OPEN as tightly as OPEN, reserving the slot until the probe reports.
  Otherwise the thread that flipped the breaker was followed straight through
  by the whole queued backlog, handing a service that had just been down
  everything at once. A probe that reports no outcome — a deliberate load
  shed does exactly that — releases the next one only when the recovery
  timeout elapses again, so recording nothing cannot also mean gating
  nothing.
- **What counts as a served reply is per-service.** TTS answers `200` with a
  JSON error body when synthesis fails, which the pipeline has always treated
  as a failure; classifying on the status code alone left the breaker CLOSED
  while every synthesis failed. `call_ai_service` takes an optional `served`
  predicate, consulted only for 2xx so malformed client input still cannot
  open a breaker.
- **Retiring the response cache** removes the only consumer of
  `_generate_cache_key` and the `cache_stats` counters reported by
  `GET /api/health/cache` and `DELETE /api/admin/cache/clear`. Both routes are
  deleted rather than left reporting zeroes forever: nothing wrote to the
  cache, so the numbers were a standing lie, and no monitoring, frontend or
  deployment config referenced either. A test asserts the 404.

## Migration Plan

Commits are ordered so nothing is ever half-wired:

1. Breaker sync API + tests (no caller yet).
2. Test-isolation fixture in a root `conftest.py`, before any call site can trip state.
3. `ai_service_client` + failure-policy tests (no caller yet).
4. Move the five pipeline call sites; add `UPSTREAM_CIRCUIT_OPEN` handling.
5. Wire live breaker transitions into the degradation mode.
6. Delete the fabricating fallbacks and their tests.
7. Delete the unreachable async client methods and their tests.

Rollback is per commit; 4 is the only one that changes runtime behaviour on the
request path.

## Open Questions

- `failure_threshold=3` / `recovery_timeout=45` were tuned for health polling.
  Correct for inference? Revisit once there is live data.
- Should a breaker opening raise an alert, or is the Prometheus series enough?
