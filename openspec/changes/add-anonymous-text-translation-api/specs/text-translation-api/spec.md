## ADDED Requirements

### Requirement: Shared-key versioned text translation

When enabled, the gateway SHALL serve `POST /api/v1/translate` with a fixed server-configured API key in `X-API-Key`, without Keycloak login,
per-user key management, tenant selection or conversation creation. It SHALL accept
explicit supported `source_lang` and `target_lang` codes and a `text` array of
1–10 nonblank strings totaling at most 5,000 Unicode code points. It SHALL
reject unknown fields and non-string entries without coercion. It SHALL return
`translations` objects containing `text`, in input order, plus `source_lang`
and `target_lang`, or fail the whole request without partial results.

#### Scenario: Authenticated ordered batch

- **WHEN** a caller presenting the configured shared API key submits two valid texts and supported languages
- **THEN** the API returns two translation objects in the same order without
  creating a session or invoking ASR, TTS or refinement

#### Scenario: Invalid or oversized request

- **WHEN** a request has invalid fields, blank entries or unsupported languages
- **THEN** the API returns 422 before inference
- **WHEN** a request exceeds the body, entry-count or total-character bound
- **THEN** the API returns 413 with the applicable published limit before inference

#### Scenario: Identical supported languages

- **WHEN** source and target are the same supported language
- **THEN** the API returns each original input unchanged without inference

### Requirement: Actual translation capabilities

The gateway SHALL serve shared-key-protected `GET /api/v1/languages` as a `languages`
array of canonical codes from the intersection of installed translation
capabilities and the installation API allowlist. Translation SHALL validate
against that same set independently of guest UI and TTS language lists.

#### Scenario: Capabilities unavailable

- **WHEN** the API cannot establish installed translation capabilities
- **THEN** language discovery returns 503 rather than an invented language list

### Requirement: Bounded automatic segmentation without silent truncation

The translation service SHALL count actual model tokens including special
tokens, preflight all segments before inference, split long text automatically
and preserve paragraph structure and result ordering. Strict-mode encoding
SHALL NOT silently truncate input. Generation that reaches its output cap
without a valid end-of-sequence SHALL trigger bounded subdivision recovery or
an explicit error. Every attempt SHALL consume one request-wide finite work
budget and deadline. Tokenizer mutation and encoding SHALL remain concurrency safe.

#### Scenario: Long text within the request budget

- **WHEN** valid text exceeds a single segment's token target
- **THEN** it is split at paragraph, sentence or smaller safe boundaries,
  translated and reconstructed without omitting input due to truncation

#### Scenario: Output stops at its cap

- **WHEN** generation reaches its cap without a valid end-of-sequence
- **THEN** the service subdivides and retries within the remaining budget
- **AND** if recovery cannot complete, the API returns an explicit error
  instead of a partial success

#### Scenario: Work budget exceeded before inference

- **WHEN** tokenization shows that the entire batch exceeds the segment budget
- **THEN** the API returns 413 with the applicable limit before inference

### Requirement: Bounded anonymous resource consumption

Anonymous translation SHALL have finite configured body, rate, concurrency,
queue, segment/retry and total-time limits. It SHALL reuse translation service
admission and circuit breakers. Rate limits SHALL use only trusted proxy
client-address resolution. V1 laboratory enablement SHALL NOT require a
dedicated load test: the owner waived that gate on 2026-11-17 based on stable
observed server utilization and the expected rare laboratory workload. This
waiver SHALL NOT disable admission, priority or finite work limits. Missing
configuration SHALL NOT permit unbounded work.

#### Scenario: Rate or capacity exhausted

- **WHEN** the caller exceeds its rate allowance
- **THEN** the API returns 429 with Retry-After
- **WHEN** admission capacity is exhausted
- **THEN** the API returns 503 with error code `SYSTEM_BUSY` and Retry-After

#### Scenario: Cancellation or deadline

- **WHEN** the request is cancelled or its total deadline expires
- **THEN** no further segments are scheduled and running inference retains
  its slot until its worker finishes
- **AND** a processing deadline with an available HTTP response receives 504;
  expiry while waiting for capacity receives 503 with `SYSTEM_BUSY` and Retry-After

### Requirement: Conversation priority for laboratory API work

V1 SHALL use a bounded ephemeral queue and synchronous HTTP responses without
durable jobs, job IDs or result polling. At the inference dispatch boundary,
conversation translations SHALL take priority over API segments. At most one
API segment SHALL execute at a time, and no new API segment or retry SHALL
start while a conversation message pipeline is active in ASR, translation,
refinement or TTS. Unknown conversation activity SHALL pause API dispatch.
An idle open session SHALL NOT block API work. The implementation SHALL NOT
claim preemption or unchanged conversation latency on a shared GPU.

#### Scenario: Conversation arrives during API work

- **WHEN** a conversation message starts processing during an API inference
- **THEN** the current API segment may finish but further API segments wait
  until conversation processing is idle
- **AND** pending conversation translations are dispatched before API segments

#### Scenario: Sessions are open but idle

- **WHEN** sessions exist but no conversation message pipeline is active,
  no conversation translation is pending and API capacity is available
- **THEN** a queued API segment is eligible for execution

#### Scenario: Sustained conversation traffic

- **WHEN** conversation activity prevents an API request from finishing before
  its total deadline
- **THEN** it expires with 503, error code `SYSTEM_BUSY` and Retry-After
  rather than bypassing conversation priority

#### Scenario: Background dispatch state is unknown

- **WHEN** the dispatcher cannot establish conversation activity
- **THEN** no new API segment starts

### Requirement: Stateless private content handling

Anonymous translation SHALL NOT persist input or output content in sessions,
Redis, analytics, logs or traces. Responses SHALL carry `Cache-Control:
no-store`. Aggregate operational metrics SHALL NOT contain text or caller
identifiers as labels. The API SHALL NOT expose model generation overrides,
internal debug information or device details.

#### Scenario: Translation completes or fails

- **WHEN** an anonymous translation completes or fails
- **THEN** no input or output content is written to application persistence,
  logs, traces or analytics, and the response disables caching

### Requirement: Fixed shared client API key

Both public endpoints SHALL require the fixed server-configured key from
`SSF_TEXT_TRANSLATION_API_KEY` in the `X-API-Key` header. Missing or incorrect
keys SHALL return 401 with `INVALID_API_KEY` before reading translation input,
caller rate accounting or upstream calls. Comparison SHALL use constant-time
comparison. An enabled installation without a configured key SHALL fail closed
with 503. The client key SHALL remain separate from the internal callback token
and SHALL NOT be committed, logged or returned in errors.

#### Scenario: Missing or incorrect client key

- **WHEN** a caller omits the header, presents an incorrect key or supplies
  the internal service token as a client key
- **THEN** either public endpoint returns 401 `INVALID_API_KEY` with no-store
  and performs no upstream operation or caller rate accounting

#### Scenario: Server key is not configured

- **WHEN** the feature is enabled without a fixed client key
- **THEN** public endpoints return 503 and never allow anonymous fallback
