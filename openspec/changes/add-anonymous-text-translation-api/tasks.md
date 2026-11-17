## 1. Contract and operating limits

- [x] 1.1 Review and approve this proposal and its gateway architecture delta.
- [x] 1.2 Choose finite token, segment/retry and deadline limits and verify
  strict segmentation and output recovery with hermetic tests. GPU benchmark
  tuning is optional for laboratory V1.
- [x] 1.3 Document finite body, rate, concurrency and queue limits and trusted
  proxy/replica behavior. Mixed-load measurement was waived by the owner on
  2026-11-17 for rare laboratory use.
- [x] 1.4 Define authoritative conversation-pipeline activity ownership and its
  dispatch signal, including cancellation, unknown state and deployment scope.

## 2. Strict translation service mode

- [x] 2.1 Implement tokenizer-aware preflight segmentation with multilingual
  boundaries, paragraph reconstruction and no input truncation.
- [x] 2.2 Detect output-cap termination and implement bounded subdivision retries
  under one work budget and deadline, preserving legacy callers' contract.
- [x] 2.3 Admit bounded segment work and retain slot ownership until running
  inference completes, including timeout and cancellation paths. Prioritize
  conversations, allow at most one API segment at once and pause new API work
  while any conversation message pipeline is active.
- [x] 2.4 Test exact token boundaries, long sentences, text without spaces,
  paragraph preservation, concurrent language encoding, output-cap recovery,
  non-progress, budget exhaustion and cancellation.
- [x] 2.5 Test conversation priority at segment boundaries, ASR/TTS activity,
  unknown activity, idle sessions and intentional API expiry under sustained
  conversation traffic.

## 3. Anonymous gateway API

- [x] 3.1 Add lifespan-owned translation collaborators and thin versioned routes,
  strict request/response models and the installation enable flag.
- [x] 3.2 Add published capability lookup, character/entry/body validation,
  trusted-proxy-aware rate limiting and bounded anonymous admission.
- [x] 3.3 Reuse the translation circuit breaker; map failures, Retry-After,
  deadline and incomplete-result errors into the API contract.
- [x] 3.4 Add aggregate metrics and no-store responses; verify payloads never
  enter conversation persistence, content logs or traces.
- [x] 3.5 Test anonymous success, ordered batching, identical languages, every
  limit, unsupported fields/languages, overload, upstream failure and deadline.

## 4. Compatibility and release

- [x] 4.1 Run gateway contract checks, deliberately update the OpenAPI snapshot,
  and verify retired routes, tenant isolation and conversation behavior.
- [x] 4.2 Run focused translation tests and relevant required checks.
- [x] 4.3 Document the English quickstart, API error/limit contract, operating
  configuration and rollback.
- [x] 4.4 Record the owner's 2026-11-17 waiver of the dedicated load test based
  on stable observed utilization and sufficient capacity; no load test was run.
- [ ] 4.5 Enable laboratory ingress when deployment is requested; V1 remains
  off by default. The dedicated load test is no longer a prerequisite.

## Verification status

Implementation is authorized by the user and complete. Operating limits are
finite conservative defaults. The owner waived the dedicated load test;
real-GPU benchmarking remains optional tuning, not a completed validation claim. No deployment
or feature enablement has been performed.

Final hermetic verification using the project-pinned CI environment: 5,290 passed,
52 skipped and 14 deselected. Gateway MyPy: no issues in 215 source files.
Black, isort, scoped Flake8, OpenSpec strict validation and diff whitespace
checks passed. Code review has no remaining material findings.
