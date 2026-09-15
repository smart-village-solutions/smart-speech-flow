# Feedback Persistence and Quality-Telemetry Correlation Design

This design is the approved solution for collecting and retaining feedback from
the FeedbackSheet.

## Decision

Structured feedback belongs in the existing ClickHouse analytics pipeline;
free-text feedback belongs in a separate encrypted transactional repository.
The Gateway is the sole place that correlates a submitted session with its
pseudonymous analytics reference.

## Data Flow

```text
FeedbackSheet -> POST /api/feedback -> Gateway
                                      |- feedback repository (authoritative)
                                      `- OTLP -> Collector -> ClickHouse (analytics)
```

The repository stores the optional text, `feedback_id`, consent/purpose
snapshot, `retention_policy_version`, `created_at`, and `expires_at`. ClickHouse
receives a `feedback_submitted` event with ratings, NPS, form version,
`session_ref`, and a keyed hash of `feedback_id`; it never receives the text.

Submitting the voluntary form is the active agreement to the disclosed
processing purpose and twelve-month storage. A concise notice and withdrawal
route appear beside the submit action; no separate checkbox is required.

## Retention

Free-text feedback expires 12 months after submission. The expiry processor
deletes the repository record and produces a content-free audit entry. A future
policy-control capability will version new retention policies; it will not alter
past expiry dates without a deliberate migration.

## Reliability

The repository write is authoritative: the user receives success only after it
commits. Analytics emission is best-effort and independently reconciled,
therefore a telemetry outage cannot lose an otherwise accepted feedback
submission.

The full requirements, API rules, data model, risks, and verification plan are
in `openspec/changes/add-feedback-persistence/design.md`.
