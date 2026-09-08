# Change: Add privacy-governed feedback persistence

## Why

The frontend already collects three ratings, an NPS score, and optional free
text, but currently sends them to an in-memory stub. SSF therefore cannot use
the feedback KPIs or retain improvement ideas for authorised follow-up.

ClickHouse is suitable for the pseudonymised, structured analytical part of a
submission, but free text can contain personal or sensitive information and
must not enter the telemetry pipeline.

## What Changes

- Add an authenticated gateway feedback endpoint and validate a feedback
  submission against a known session.
- Store feedback free text in a separate encrypted transactional feedback
  repository with role-restricted, audited access and a 12-month retention
  period.
- Emit a typed, allowlisted `feedback_submitted` quality event for the ratings
  and NPS through the existing OTLP-to-ClickHouse pipeline.
- Link the two records with a gateway-generated `feedback_id`; ClickHouse holds
  only a keyed hash of that identifier and the existing pseudonymised
  `session_ref`.
- Add expiry and deletion processing, including the data model needed for a
  later retention-policy control without implementing its administration UI.

## Impact

- Affected capability: quality telemetry and new feedback persistence.
- Affected code: frontend feedback sink, API Gateway route and models,
  telemetry contract, ClickHouse migrations, feedback repository, retention
  worker, access audit, and tests.
- Dependency: `add-clickhouse-quality-telemetry` provides the existing OTLP,
  pseudonymisation, and ClickHouse medallion pipeline.

## Non-Goals

- Storing feedback free text, raw session IDs, personal data, IP addresses, or
  free-form errors in ClickHouse, OpenTelemetry, or application logs.
- An administrator UI for reading feedback or configuring retention policies.
- A general consent/content platform beyond the feedback-specific safeguards
  required here.
