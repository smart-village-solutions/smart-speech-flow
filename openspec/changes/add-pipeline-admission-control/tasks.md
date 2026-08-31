# Tasks

## 1. Admission component

- [x] 1.1 Add `services/api_gateway/pipeline_admission.py` with
  `PipelineAdmissionConfig`, `PipelineAdmissionMetrics`, `PipelineAdmission`,
  `PipelineBusyError` and the `run_pipeline` request helper.
- [x] 1.2 Read `MAX_CONCURRENT_PIPELINES` and `PIPELINE_QUEUE_WAIT_SECONDS` per
  instance, falling back to documented defaults on unparseable or negative
  input. Only an explicit `0` disables the bound.
- [x] 1.3 Register the in-flight, queue-wait and rejection series once per
  process against the gateway registry. Observe the queue wait on the rejection
  path as well, so the histogram is not blind at saturation.
- [x] 1.4 Hold slots against the worker thread's lifetime, not the awaiting
  task: `run()` releases from inside the thread, because `asyncio.to_thread`
  cannot interrupt a running call and a cancelled request must not hand its
  capacity to the next caller.

## 2. Wiring

- [x] 2.1 Create the component in the app lifespan and publish it on
  `app.state.pipeline_admission`; clear it on shutdown.
- [x] 2.2 Bound the audio and text paths of `POST /api/session/{id}/message`
  around the GPU call only.
- [x] 2.3 Bound `POST /pipeline` and `POST /upload`; `upload()` takes a
  `request` parameter so it can reach application state.
- [x] 2.4 Translate `PipelineBusyError` into each route's own error shape with
  `503` and `Retry-After`.

## 3. Tests

- [x] 3.1 Config defaults, environment override and unparseable fallback.
- [x] 3.2 Bounding: admits to the limit, rejects beyond it, returns slots after
  success and after an exception, hands a freed slot to a waiter, `0` disables.
- [x] 3.3 `SYSTEM_BUSY` contract on both paths of the unified endpoint, and that
  the broad `except Exception` in `send_unified_message` does not mask it as 500.
- [x] 3.4 Both legacy routes reject with `503` and `Retry-After`.
- [x] 3.5 Session-management and health traffic stay responsive at saturation.
- [x] 3.6 Metrics move; lifespan publishes the component; no module singleton.
- [x] 3.7 A cancelled request keeps its slot until its thread finishes, and the
  slot becomes reusable afterwards.
- [x] 3.8 End-to-end over HTTP: env -> lifespan -> `app.state` -> route ->
  `503` with the `Retry-After` header actually on the wire.
- [x] 3.9 Body and header advise the same delay.
- [x] 3.10 Watch the suite fail with a gate removed, and with the slot released
  from the awaiting task, then restore both.

## 4. Documentation

Only tracked files count here: `LOCAL_SETUP.md` and `docs/frontend/` are in
`.git/info/exclude`, so anything written there is invisible to a reviewer.

- [x] 4.1 Document the `SYSTEM_BUSY` consumer contract where consumers will find
  it: the `503` entry under `/api/session/{sessionId}/message` in the tracked
  `docs/openapi.yaml`, including client handling, and the route's FastAPI
  `responses=` dict so it reaches the generated schema too.
- [x] 4.2 Document both settings in `.env.example` and `docker-compose.yml`.
- [x] 4.3 Record the frontend impact in this change's `proposal.md`.
- [x] 4.4 Local-only additions, not a substitute for the above: the operator
  tuning guide in `LOCAL_SETUP.md` and the fuller narrative in
  `docs/frontend/API_CONTRACT.md`.

## 5. Follow-ups (not this change)

- [ ] 5.1 Raise `MAX_CONCURRENT_PIPELINES` from load-test evidence.
- [ ] 5.2 Optional `AppError` `busy` kind and a dedicated i18n message.
- [ ] 5.3 Cross-replica admission (#227).
