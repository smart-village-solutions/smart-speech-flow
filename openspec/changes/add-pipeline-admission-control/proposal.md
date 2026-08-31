# Change: Add bounded pipeline admission control and a SYSTEM_BUSY response

Tracks: #191 (ships with #189)

## Why

Until #189, the gateway called `process_wav` and `process_text_pipeline`
synchronously from `async def` handlers, so its event loop serialised every
pipeline. That accidental serialisation was the only thing protecting GPU
capacity. Removing it removes the protection too.

The hardware behind those calls is one RTX 4000 Ada that hosts ASR, translation
and TTS at the same time, and each of those services holds a single shared model
instance with no lock of its own (`services/asr/app.py:132`,
`services/tts/app.py:143`). Unbounded concurrency there means concurrent CUDA
work on one shared model per service, competing for one card's memory.

Clients also need an answer better than a timeout when the system is full.

## What Changes

- Add a lifespan-owned `PipelineAdmission` component bounding in-flight
  pipelines, with a configurable queue wait before rejection.
- Apply the bound around the GPU call only, at all four call sites:
  `POST /api/session/{id}/message` (audio and text), `POST /pipeline`,
  `POST /upload`. Health, session-management and WebSocket traffic are untouched.
- Reject saturation with `503`, a `Retry-After` header and a stable
  `SYSTEM_BUSY` error code in the endpoint's existing error envelope.
- Emit in-flight, queue-wait and rejection metrics so load tests can tune the
  limit.
- Document the consumer contract and the configuration.

## Impact

- Affected specs: `pipeline-admission-control` (new capability)
- Affected API gateway: new `pipeline_admission` module, lifespan wiring,
  the four pipeline call sites, and `upload()` gains a `request` parameter.
- Affected frontend: **none.** `core/http/AppError.ts` maps status codes without
  reading the response body, so a `503` already becomes `AppError('server')` and
  surfaces as `errors.server`. A dedicated `busy` kind is a possible follow-up,
  not part of this change.
- Affected configuration: `MAX_CONCURRENT_PIPELINES` (default `2`),
  `PIPELINE_QUEUE_WAIT_SECONDS` (default `10.0`).
- Not affected: cross-replica coordination. The bound is process-local; a
  distributed queue and queue-position UX remain #227.

## Open question for review

The default limit of `2` is inferred from the hardware, not measured — no
pipeline throughput benchmark exists in the repository. The metrics in this
change exist so the figure can be raised from evidence. `0` disables the bound.
