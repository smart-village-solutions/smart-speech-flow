# Change: Add bounded pipeline admission control and a SYSTEM_BUSY response

Tracks: #189, #190, #191 — the set #191 asks to ship together

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

The translation service has the same defect one layer down (#190): its
`async def translate` calls `_translate_texts` inline, so `m2m_model.generate()`
holds that service's only loop thread for the whole beam search. Its `/health`
and `/metrics` handlers are synchronous and would run in a threadpool, but the
blocked loop never gets as far as accepting the connection. Fixing the gateway
alone would leave translation as the real serialisation point, so raising
`MAX_CONCURRENT_PIPELINES` would buy nothing.

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
- Run translation inference on a worker thread and bound it the same way, with
  `MAX_CONCURRENT_TRANSLATIONS` and `TRANSLATION_QUEUE_WAIT_SECONDS`, rejecting
  saturation with `503` and `Retry-After`. The tokenizer lock that guards the
  mutable `src_lang` becomes load-bearing here and is covered by a test that
  proves mutual exclusion.
- Document the consumer contract and the configuration.

## Impact

- Affected specs: `pipeline-admission-control` (new capability)
- Affected API gateway: new `pipeline_admission` module, lifespan wiring,
  the four pipeline call sites, and `upload()` gains a `request` parameter.
- Affected frontend: **none.** `core/http/AppError.ts` maps status codes without
  reading the response body, so a `503` already becomes `AppError('server')` and
  surfaces as `errors.server`. A dedicated `busy` kind is a possible follow-up,
  not part of this change.
- Affected translation service: inference offloaded to a worker thread, a
  lifespan-owned `TranslationAdmission`, and a `503` with `Retry-After` on
  saturation.
- Affected configuration: `MAX_CONCURRENT_PIPELINES` (default `2`),
  `PIPELINE_QUEUE_WAIT_SECONDS` (default `10.0`),
  `MAX_CONCURRENT_TRANSLATIONS` (default `2`),
  `TRANSLATION_QUEUE_WAIT_SECONDS` (default `25.0`, under the gateway's 30s
  timeout for `/translate`).
- Also fixed, and not covered by any issue: the ASR, translation and TTS
  Dockerfiles copy `services/gpu_metrics.py` but never
  `services/resource_metrics.py`, which all three import at module level since
  `1fb7f09`. As committed, those three images raise `ImportError` at startup;
  production is only healthy because it runs an image built before that commit.
- Not affected: cross-replica coordination. The bound is process-local; a
  distributed queue and queue-position UX remain #227. ASR and TTS already
  offload their inference and are left alone; neither is bounded yet.

## Open question for review

The default limit of `2` is inferred from the hardware, not measured — no
pipeline throughput benchmark exists in the repository. The metrics in this
change exist so the figure can be raised from evidence. `0` disables the bound.
