# Anonymous Text Translation API Implementation Plan

> **For agentic workers:** Use subagent-driven-development for the isolated translation and gateway tasks; integrate and review all boundaries before completion.

**Goal:** Provide opt-in anonymous synchronous laboratory translation with bounded text segmentation and conversation priority.

**Architecture:** A gateway facade validates requests and admits a small in-memory queue. The translation service performs strict tokenizer-aware segmentation and checks authoritative gateway pipeline activity before dispatching each background segment. Already running inference is never considered preempted.

**Tech Stack:** Python 3.12, FastAPI, requests, asyncio, M2M100, pytest.

**Spec:** `openspec/changes/add-anonymous-text-translation-api/design.md`

## Global Constraints

- V1 has no login, user API keys, durable jobs or additional broker.
- Accept 1–10 nonblank strings totaling at most 5,000 Unicode code points.
- Preserve paragraphs; reject incomplete generation instead of silently truncating.
- Run at most one background segment; unknown conversation activity pauses dispatch.
- Feature stays disabled by default; dedicated load testing was waived by the owner on 2026-11-17.
- Never persist or log request or result text.

## Task 1: Strict translation engine and internal endpoint

Files: new `services/translation/strict_text.py`, modify `services/translation/app.py` and Dockerfile; tests in `services/translation/tests/test_strict_text.py`.

Interface: POST `/translate/text`, internal shared `X-SSF-Lab-Token`, body `{text, source_lang, target_lang, timeout_seconds}`, result `{translations: list[str]}`. Before each segment query the configured gateway activity endpoint; unknown or busy waits within the total deadline. Errors carry `detail.code` and `detail.message`.

- [x] Write and run failing tests for token-aware segmentation, paragraphs, no-space input, capped-output retries and budget exhaustion.
- [x] Implement strict segmentation with exact tokenizer counts and no truncation; finite segment/retry and decoder token budgets.
- [x] Write and run failing endpoint tests for authentication, malformed payload, ordering, unknown/busy activity and deadline.
- [x] Add per-segment admission, bounded background concurrency and strict completion checks. Preserve legacy `/translate` behavior.
- [x] Run translation tests and review internal adapter failures without exposing text.

## Task 2: Gateway laboratory facade

Files: new `services/api_gateway/text_translation.py` and `routes/text_translation.py`; modify dependency composition and route registration; tests in `tests/test_text_translation_api.py`.

Interface: anonymous POST `/api/v1/translate`, GET `/api/v1/languages`; collaborator uses existing registered translation breaker. Defaults: disabled; body 65,536 bytes; four queued requests plus one running; deadline 30 seconds; six requests per IP per minute with finite IP tracking. Socket address is authoritative; proxy headers are ignored unless handled by trusted server proxy configuration.

- [x] Write and run failing anonymous HTTP contract tests for ordered results, language lookup, disabled feature, field limits, error mapping and no-store.
- [x] Implement strict models, streamed body limit, bounded queue and per-IP rate limit with lifespan-owned dependencies.
- [x] Test full queue, cancellation, global deadline, upstream failures and malformed results; implement required handling.
- [x] Register routes and regenerate the deliberate OpenAPI snapshot after review.

## Task 3: Conversation activity and integration

Files: gateway pipeline admission, new internal activity route, Compose, English documentation, OpenSpec task status.

Interface: GET `/internal/text-translation/activity`, same internal token, response `{busy: bool}`; no token or missing admission is an explicit unavailable response. Counts include queued pipelines and running worker lifetime after HTTP cancellation.

- [x] Write failing activity tests including queued/running work and cancellation.
- [x] Expose authoritative pending plus executing pipeline activity; protect internal endpoint with constant-time token comparison.
- [x] Configure the token and callback only when enabled; keep laboratory enablement opt-in and document single-scheduler deployment.
- [x] Run focused suites, gateway contract and relevant hermetic checks, formatting and gateway typing.
- [x] Review all changes for concurrency, privacy, compatibility and spec compliance; record the owner's load-test waiver without claiming a benchmark.

## Verification outcome

The implementation and code review are complete. The final hermetic suite
passed 5,290 tests (52 skipped, 14 deselected) using pinned CI dependencies in
a clean source worktree. Gateway typing passed for 215 modules; formatting,
scoped lint, OpenSpec strict validation and whitespace checks passed.

Deployment and a real-GPU mixed-load test were not performed. On 2026-11-17
the owner waived dedicated load testing for rare laboratory use based on stable
observed utilization. The feature remains disabled by default; explicit
deployment/enablement is the remaining operational step in OpenSpec.
