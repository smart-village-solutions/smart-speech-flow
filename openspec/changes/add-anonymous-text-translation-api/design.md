## Context

The gateway currently exposes processing through tenant-aware conversation
routes. `HttpSpeechServices.translate` already calls the internal service
through its registered circuit breaker with a 30-second timeout. Translation
inference runs on worker threads under service admission control, sharing GPU
resources with live ASR, translation, TTS and refinement.

The current translation defaults are 1,024 input tokens, 256 new output tokens
and character-based splitting only above 20,000 characters. Encoding uses
`truncation=True`; splitting by character count does not guarantee that an
input fits. Reaching the output token cap can also leave a translation
unfinished. Neither behavior is acceptable for the new public API.

## Goals and non-goals

The intended V1 workload is occasional laboratory use. Provide anonymous
synchronous plain-text translation, automatic bounded
segmentation and a stable external contract. No conversation creation, tenant
selection, authentication, API-key management, ASR, TTS, LLM refinement,
HTML/document translation, automatic language detection or persisted jobs.
Do not add a durable job queue, external broker, job IDs or result polling.

## Public contract

`POST /api/v1/translate` accepts JSON with exactly these fields:

```json
{
  "text": ["Guten Tag.", "Bitte bringen Sie Ihren Ausweis mit."],
  "source_lang": "de",
  "target_lang": "en"
}
```

All entries must be strings containing non-whitespace content. Reject unknown
fields and implicit coercion of numbers, objects or nulls. Require 1–10
entries and at most 5,000 Unicode code points summed across the original
strings, including whitespace. Document the count explicitly; bytes and UTF-16
code units are not the character unit. Source and target codes are canonical
lowercase service codes. Validate both against the API's published allowlist.

```json
{
  "translations": [{"text": "Good afternoon."}, {"text": "Please bring your ID with you."}],
  "source_lang": "de",
  "target_lang": "en"
}
```

Return all results in order or an error; never return a partly successful
array. For identical supported source and target languages, return the input
unchanged without inference. Successful processing is not a guarantee of
semantic translation accuracy.

`GET /api/v1/languages` returns `{"languages": ["de", "en"]}` using the actual
validated intersection of installed translation capabilities and an
installation-wide API allowlist. This is independent of guest UI languages
and TTS support. If capabilities are unavailable, return 503 rather than an
invented list. Language-pair restrictions, if introduced, need an explicit
contract instead of being inferred from conversation behavior.

Use `{"error": {"code": "...", "message": "...", "limits": {...}}}` for
expected API errors; include `limits` only when useful. Use 400 for malformed
JSON, 422 for invalid fields or unsupported languages, 413 for body, character,
entry-count or preflight work limits, 429 with `Retry-After` for caller rate
limits, 503 with `Retry-After` for saturation/unavailability, 504 for a processing
deadline, and 502 for an unusable upstream result or incomplete generation
after bounded recovery. Framework-level unexpected failures retain the
gateway's established sanitized 500 policy. Capacity failures SHALL carry the
stable public code `SYSTEM_BUSY`. This includes a full queue and expiry while
waiting for conversation priority to permit dispatch; both return 503 with
`Retry-After`. A processing timeout is distinct from capacity waiting. Rate
rejections use 429 with `RATE_LIMIT_EXCEEDED`.

## Automatic segmentation and completeness

Keep segmentation and generation in the translation service, where the exact
tokenizer and model configuration exist. The gateway owns external validation
and orchestration. Introduce a strict internal mode for this API; legacy
conversation callers retain their current contract unless separately approved.
Do not expose generation overrides or debug responses publicly.

1. Identify paragraphs and sentence boundaries with multilingual behavior.
   Preserve paragraph separators for reconstruction instead of using the
   conversation normalizer, which collapses whitespace.
2. Pack complete sentences within a configured input-token target, counting
   the exact encoded sequence including special tokens. Start evaluation at
   approximately 256 tokens per segment; this is a tuning candidate, not a
   universal model or public text-length limit.
3. Split a sentence that exceeds the target at word boundaries. For text
   without word boundaries, split at Unicode-safe boundaries and retokenize
   each candidate. Ensure splitting always makes progress or fails explicitly.
4. Plan and count the segments across all entries before any inference.
   Validate against the model's real context limit; strict-mode encoding MUST
   NOT silently truncate. Protect tokenizer language mutation, token counting
   and encoding with the existing concurrency discipline.
5. Generate within a configured output budget compatible with the decoder's
   capacity. Inspect the effective end-of-sequence and generation-cap outcome
   before decoding discards special tokens. Reaching the cap without a valid
   end-of-sequence is incomplete, even if the decoded text looks plausible.
6. Retry incomplete segments only by bounded further subdivision. Charge
   every retry and additional segment to one request-wide work budget and
   deadline. If subdivision cannot progress or budgets are exhausted, fail the
   whole request explicitly; do not return partial or truncated text.
7. Reassemble ordered segments into one result per original entry, preserving
   paragraph structure. Segment boundaries can still reduce contextual and
   terminological consistency; evaluate representative multi-paragraph text.

The gateway and translation service must share the remaining deadline; the
existing 30-second upstream timeout alone is not an end-to-end work budget.
Reserve a short response margin inside that deadline so a service-side busy
response can reach the gateway before its HTTP waiter expires. Expected busy
and processing-deadline failures are neutral to the shared live inference
breaker; laboratory work cannot acquire its recovery probe.

## Capacity, cancellation and privacy

Use a small, finite in-memory queue while the synchronous HTTP request waits,
without bypassing existing service admission or breakers. Queue state and
partial results are ephemeral: cancellation, expiry or restart does not create
a resumable job. A full queue or expiry while waiting for conversation priority returns 503
with `SYSTEM_BUSY` and Retry-After; an actual processing deadline returns 504.

Give conversation translations strict priority over API segments at the
translation service's dispatch boundary. Run at most one API segment at a
time. Reconsider eligibility before every segment and subdivision retry,
rather than admitting an entire API batch to GPU execution at once.

Do not start background segments while a live conversation message pipeline
is processing ASR, translation, refinement or TTS. This requires an internal
conversation-activity signal in addition to translation-queue priority;
translation idleness alone does not imply that the shared GPU is idle. An
open but idle session does not block background work. The implementation plan
must define authoritative activity ownership, cancellation cleanup and how the
dispatch boundary observes it. Unknown activity state pauses background work;
public callers cannot supply or override priority or activity signals.

The authoritative activity observation is repeated inside the inference
worker immediately before generation, after executor and admission waiting.
This final check defines dispatch: a conversation arriving after authorization
may overlap that already-dispatched segment. There is no atomic cross-process
GPU reservation and no guarantee of zero hardware contention.

V1 targets the current single gateway/translation scheduling deployment. Do
not enable independent schedulers on multiple replicas without coordinating
the activity signal and background concurrency bound. No extra broker is
required for the intended deployment.

An API inference already running when conversation work arrives finishes its
current bounded segment; it cannot be preempted by cancelling the HTTP waiter.
Priority therefore reduces interference but cannot guarantee unchanged latency
on the shared GPU. The owner waived a dedicated load test on 2026-11-17 for the rare laboratory
workload, based on stable observed server utilization. Dedicated GPU resources are a
separate option if strict resource isolation becomes necessary.

Apply caller rate limits to a client IP derived only through trusted proxy
configuration, plus a global bound. Shared NAT users share the IP quota;
distributed callers are contained by the global bound. Document limiter scope
and replica behavior. Reject oversized streaming bodies even without a valid
Content-Length. Missing required limits must not enable unbounded execution.

Stop scheduling further segments after cancellation or deadline expiry. A
running inference retains its slot until its worker actually finishes.
The gateway detects HTTP disconnects and maintains a private, ephemeral request
reference with a cancellation event for each running strict call. That reference
is sent only to the internal service and authenticated activity callback;
unknown references fail closed as cancelled. The callback is checked before
every segment, including retries, so cancellation propagates beyond the
gateway's waiting task. This is not a public job or persisted identifier.

Do not store request or result text in Redis, conversation history, analytics,
logs or traces. Return `Cache-Control: no-store`. Metrics may record aggregate
counts, token/character volume, latency, segmentation and rejection reasons;
do not label metrics with text or caller identifiers.

## Alternatives considered

- Expose the internal service directly: smallest adapter, but publishes
  generation/debug details and weak validation without gateway controls.
- Add a gateway facade (selected): reuse inference infrastructure while
  defining a stable contract and future authentication boundary.
- Implement full DeepL compatibility: useful for unchanged client migration,
  but exceeds the agreed similarity in usability.

## Validation and laboratory release

V1 uses documented finite defaults for body size, segment/retry work, output
budgets, total deadline, concurrency, queueing and caller rate. Hermetic tests
cover segmentation, multilingual/unbroken input, output expansion recovery,
conversation priority and cancellation. The defaults are conservative choices,
not measured GPU throughput or translation-quality guarantees.

On 2026-11-17 the owner explicitly waived the dedicated load test, citing stable
server utilization, sufficient capacity and rare laboratory API usage. No load
test was performed; existing utilization is not represented as a measured
mixed-load benchmark. This removes that release prerequisite while retaining
all runtime limits and conversation priority. Further benchmarking is optional
tuning if actual laboratory use reveals a need.

Sustained conversation traffic may starve API work until its deadline and
produce 503 `SYSTEM_BUSY`; that is intentional for laboratory V1. Routes remain
opt-in through the installation flag. Rollback disables them while leaving
conversation routing and legacy internal mode intact.
