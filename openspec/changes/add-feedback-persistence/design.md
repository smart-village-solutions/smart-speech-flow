## Context

The FeedbackSheet collects translation quality, performance, usability, NPS,
and optional improvement ideas, but its `FeedbackSink` is currently a stub.
Existing quality telemetry stores only pseudonymised, allowlisted analytical
events in ClickHouse. Its explicit privacy boundary excludes free text.

## Goals / Non-Goals

### Goals

- Persist voluntary feedback reliably enough that a success response never
  silently loses its free-text submission.
- Make structured ratings available alongside `session_lifecycle` and
  `translation_message` analytics without exposing free text to ClickHouse.
- Retain free text for 12 months, with automatic deletion and a design that can
  later support retention-policy configuration.

### Non-Goals

- Build a feedback administration UI, a configurable policy UI, or a general
  content store.
- Add feedback text to dashboards or permit full-text analytics.

## Decisions

### Separate authoritative and analytical stores

The Gateway SHALL create a UUID `feedback_id` for each accepted submission.
It writes the authoritative feedback record to an encrypted transactional
feedback repository, then makes a best-effort emission of a structured
`feedback_submitted` event through the existing OTLP Collector to ClickHouse.

The repository row contains `feedback_id`, the optional free text, creation and
expiry timestamps, `retention_policy_version`, the purpose/consent snapshot,
and minimal processing metadata. The free text is encrypted at rest; reads are
restricted by role and recorded in an access audit.

The analytics event contains ratings, NPS, form version, submission time,
`session_ref`, and `feedback_ref` (a keyed hash of `feedback_id`). It contains
no free text, raw session ID, user identity, consent prose, IP address, or
user-agent string.

### Server-owned correlation

The frontend can submit a session identifier solely to address the API. The
Gateway validates that it exists and derives the existing keyed-HMAC
`session_ref`; it never accepts a client-provided `session_ref`, `feedback_id`,
or feedback reference. This permits aggregate joins to session and message
telemetry while keeping ClickHouse pseudonymised.

### Delivery semantics

The transactional repository is authoritative. The endpoint returns success
only after its write has committed. A ClickHouse or Collector outage does not
turn a stored feedback submission into an API failure. The system records an
idempotent pending-analytics marker with the repository row and a reconciler
re-emits its event with the same event ID until accepted by the local emitter.
The operational limitation remains: the current OTel path is lossy after its
in-memory queue; the reconciler can cover failed emission attempts but cannot
prove a Collector-accepted event reached ClickHouse.

### Retention and deletion

`expires_at` is set to 12 months after creation according to
`retention_policy_version`. A scheduled deletion job permanently deletes the
encrypted text and its feedback row after expiry, and writes a content-free
deletion audit. A future policy control creates new policy versions; it does
not retroactively change existing expiry dates without an explicit migration.

ClickHouse retains the feedback analytics event under the quality telemetry
retention rules. It is not a copy of the free text and cannot reconstruct it.

## API Contract

`POST /api/feedback` accepts:

- `session_id`: required existing session identifier.
- `translation_quality`, `performance`, `usability`: integers 1 through 5.
- `net_promoter_score`: integer 0 through 10.
- `improvements`: optional string of at most 4,000 Unicode characters.
- `form_version`: a server-recognised form version; defaults to the current
  version only during the initial rollout.

The endpoint returns `201 Created` with an opaque confirmation ID. It returns
validation errors for invalid ratings or oversize text, and `404` for an
unknown session. A terminated session remains eligible for feedback while it
is retained by the session manager.

## ClickHouse Model

`feedback_submitted` extends the typed event contract and projects to
`quality_events` with the following additional typed columns:

- `feedback_ref` (`String`, high-cardinality opaque reference)
- `translation_quality`, `performance`, `usability` (`UInt8`)
- `net_promoter_score` (`UInt8`)
- `feedback_form_version` (`LowCardinality(String)`)

The silver table remains the correlation source for its 30-day raw retention.
A dedicated feedback daily aggregate is preferred over extending the existing
refinement-oriented gold table: it aggregates count, response-rate numerator,
and rating/NPS distributions by date, deployment, form version, language pair,
and input mode without mixing unrelated latency states.

## Failure Handling

- Repository unavailable: reject the submission; the UI shows a retryable
  failure and must not show the thank-you state.
- Telemetry unavailable: commit the repository row, return success, surface a
  content-free operational metric, and retry reconciliation.
- Logging/telemetry serialization: free text is structurally unavailable to
  both paths; no exception handler may include request bodies in logs.

## Verification

- Unit tests validate bounds, text length, server-owned pseudonymisation, and
  telemetry allowlisting.
- Integration tests prove text is absent from logs, OTLP records, bronze,
  silver, and gold ClickHouse tables.
- Tests cover repository failure, telemetry failure, retry idempotency, 12-month
  expiry, deletion audit, and correlation to lifecycle/message records.
