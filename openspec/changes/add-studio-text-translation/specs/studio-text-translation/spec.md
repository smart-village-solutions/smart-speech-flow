## ADDED Requirements

### Requirement: Studio text translation through SSF v1

The SSF gateway SHALL offer opt-in language discovery and batch translation through its version 1 HTTP contract. It SHALL require an SSF-issued credential bound to the calling Studio instance in the `X-API-Key` header on both endpoints.

#### Scenario: Studio verifies the provider

- **WHEN** Studio calls `GET /api/v1/languages` with the pilot credential
- **THEN** the gateway returns the SSF language list with German source support and validated target capabilities

#### Scenario: Studio translates a batch

- **WHEN** Studio calls `POST /api/v1/translate` with German source text, a supported target and a valid credential
- **THEN** the response contains exactly one translation per input in input order and retains the exact Studio protection markers in each entry

#### Scenario: Credential is missing or invalid

- **WHEN** a caller accesses either enabled endpoint without the credential authorized for the pilot
- **THEN** the gateway returns an authentication error before accepting translation work

### Requirement: Bounded background translation

The SSF gateway SHALL document and enforce request, queue and inference limits. It SHALL prioritize live conversation work over background text translation and allow no more than one pilot request to execute at a time.

#### Scenario: Request cannot be translated completely

- **WHEN** an input exceeds the supported limits, the engine detects incomplete output, or marker integrity cannot be verified
- **THEN** the gateway returns a clear error without a partial batch

#### Scenario: Background capacity is exhausted

- **WHEN** a request is refused for temporary capacity exhaustion
- **THEN** the gateway returns `503` with `Retry-After` and preserves admission priority for live conversations

### Requirement: Private and installation-scoped operation

The SSF gateway SHALL enable the Studio routes per installation. Source text, translated text and credentials SHALL be excluded from logs and telemetry. The workflow SHALL NOT persist source text or translated text.

#### Scenario: Installation has not opted in

- **WHEN** a caller requests either Studio translation route on an installation where it is disabled
- **THEN** the gateway returns `404`

#### Scenario: Pilot request completes or fails

- **WHEN** a pilot translation request completes or fails
- **THEN** operational records contain no source text, translated text or credential and the workflow creates no conversation records
