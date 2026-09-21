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
  would leave a breaker OPEN for the next test. Mitigated by an autouse
  `reset_all()` fixture in both conftests, added before the call sites move.
- **`requests` stays the transport**, so the issue's literal "asynchronous
  service-client path" is not met. What is met is one path, used by everything,
  with live breaking. Recorded here rather than hidden.
- **The health poll and real traffic now share a breaker.** A service failing
  inference while answering `/health` will trip the breaker that gates its
  health checks. That is the intended coupling — the breaker should reflect
  whether the service can do its job — but it is new behaviour.
- **Retiring the response cache** removes the only consumer of
  `_generate_cache_key` and the `cache_stats` counters reported by
  `/circuit-breaker/cache-stats`. The endpoint keeps working and reports zeroes;
  the alternative is deleting an ops endpoint, which is a wider change.

## Migration Plan

Commits are ordered so nothing is ever half-wired:

1. Breaker sync API + tests (no caller yet).
2. Test-isolation fixture (`reset_all()`), before any call site can trip state.
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
