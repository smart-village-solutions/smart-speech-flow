## MODIFIED Requirements

### Requirement: Mock serves contract v2

The Studio mock SHALL serve `/internal/plugins/ssf/v2/runtime-configuration`
and `/internal/plugins/ssf/v2/installation-content` with the same token and
scenario handling as before, and SHALL keep serving
`/internal/plugins/ssf/v1/admin-login-tenants`. Its fixtures SHALL cover a
tenant with storage `ask`, a tenant with storage `disabled`, a tenant with
`retentionHours` 0, several guest languages including one with a null icon,
and locales SSF does not support, including the removed Kurdish alias `kmr`.
Unsupported locales SHALL serve as filtering test inputs rather than supported
SSF language expectations.

#### Scenario: Disabled tenant

- **WHEN** a client reads the runtime configuration of the disabled fixture
  tenant
- **THEN** the mode is `disabled`, `retentionHours` is null and every storage
  question is null

#### Scenario: Invalid content scenario

- **WHEN** a client requests the invalid-content scenario
- **THEN** the body has a valid storage policy and a feedback question of an
  unsupported type

#### Scenario: Removed language in Studio fixture

- **WHEN** SSF consumes mock configuration containing `kmr`
- **THEN** it skips that guest language as unsupported
