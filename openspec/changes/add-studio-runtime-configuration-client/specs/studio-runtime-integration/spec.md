## ADDED Requirements

### Requirement: Studio Runtime Configuration V1 client

SSF SHALL request Runtime Configuration V1 from the fixed internal Studio path
with service authorization, the canonical Studio tenant ID, and a correlation
ID. SSF MUST validate all known fields and both revisions, MUST require the
response tenant ID to match the request, and MUST allow unknown optional V1
additions.

#### Scenario: Valid tenant configuration

- **WHEN** Studio returns a valid V1 response for the requested tenant
- **THEN** SSF accepts the configuration and preserves its configuration and authorization revisions

#### Scenario: Invalid or cross-tenant configuration

- **WHEN** a response has an invalid known field, revision, semantic constraint, or tenant ID
- **THEN** SSF rejects the response without applying configuration

#### Scenario: Studio returns a stable error

- **WHEN** Studio returns a documented V1 error envelope
- **THEN** SSF surfaces its stable code, status, and documented `retryable` value without response details
