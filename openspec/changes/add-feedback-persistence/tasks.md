## 1. Contract and Storage

- [ ] 1.1 Define request/response models, feedback event model, opaque feedback
  reference, and form-version contract.
- [ ] 1.2 Provision an encrypted transactional feedback repository with
  role-restricted access and content-free access/deletion audit records.
- [ ] 1.3 Implement `POST /api/feedback`, including server-side session
  validation and correlation reference generation.

## 2. Analytics Integration

- [ ] 2.1 Extend the quality telemetry allowlist with `feedback_submitted` and
  typed structured feedback fields.
- [ ] 2.2 Add ClickHouse migrations for silver feedback columns and a dedicated
  feedback daily aggregate.
- [ ] 2.3 Implement idempotent pending-analytics tracking and reconciliation.
- [ ] 2.4 Replace the frontend stub with an API feedback sink and retryable
  submission failure UI.

## 3. Privacy, Retention, and Operations

- [ ] 3.1 Store the purpose/consent snapshot, `retention_policy_version`, and
  `expires_at` when a submission is accepted.
- [ ] 3.2 Implement the scheduled 12-month expiry/deletion job and deletion
  audit.
- [ ] 3.3 Add operational metrics and alerts for repository writes,
  reconciliation backlog, expiry, and deletion failures.

## 4. Verification

- [ ] 4.1 Test API validation, terminated-session feedback, frontend errors,
  and idempotent retries.
- [ ] 4.2 Test that feedback text never reaches logs, OTLP, or ClickHouse.
- [ ] 4.3 Test ClickHouse projection/aggregation and correlation with existing
  session and message telemetry.
- [ ] 4.4 Test retention expiry, deletion auditing, repository outage, and
  telemetry outage independently.
