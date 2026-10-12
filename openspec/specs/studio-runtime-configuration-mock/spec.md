# studio-runtime-configuration-mock Specification

## Purpose
Defines the local Studio mock that serves the v2 runtime configuration and installation content endpoints, with fixtures and failure scenarios, so SSF can be developed and tested without the real Studio.

## Requirements

### Requirement: Mock serves contract v2

The Studio mock SHALL serve `/internal/plugins/ssf/v2/runtime-configuration`
and `/internal/plugins/ssf/v2/installation-content` with the same token and
scenario handling as before, and SHALL keep serving
`/internal/plugins/ssf/v1/admin-login-tenants`. Its fixtures SHALL cover a
tenant with storage `ask`, a tenant with storage `disabled`, a tenant with
`retentionHours` 0, several guest languages including one with a null icon, a
locale that maps to an SSF alias and a locale SSF does not support.

#### Scenario: Disabled tenant

- **WHEN** a client reads the runtime configuration of the disabled fixture
  tenant
- **THEN** the mode is `disabled`, `retentionHours` is null and every storage
  question is null

#### Scenario: Invalid content scenario

- **WHEN** a client requests the invalid-content scenario
- **THEN** the body has a valid storage policy and a feedback question of an
  unsupported type
