## ADDED Requirements

### Requirement: Production ACME router hosts are deployable

The production deployment guard SHALL reject the rendered Compose configuration before
container reconciliation when an ACME-enabled router contains a local-only or
DNS-unresolvable hostname.

#### Scenario: Retired or local-only hostname is configured

- **WHEN** a router using the `le` certificate resolver contains `localhost` or a
  hostname that cannot be resolved by the production host
- **THEN** the deployment guard fails with an actionable hostname error
- **AND** it does not run `production_compose up -d`

#### Scenario: Public ACME router hostname is configured

- **WHEN** every router using the `le` certificate resolver contains a publicly
  resolvable hostname
- **THEN** the deployment guard permits the deployment

### Requirement: Retired archive frontend is absent from production

The canonical production Compose configuration SHALL NOT define the retired
`frontend-archive` service or its `translate-archive.smart-village.solutions` router.

#### Scenario: Production configuration is rendered

- **WHEN** the canonical production Compose configuration is rendered
- **THEN** it contains neither `frontend-archive` nor
  `translate-archive.smart-village.solutions`
