## ADDED Requirements

### Requirement: Traefik reads tenant routers from a dedicated directory

The Kassel deployment SHALL enable Traefik's watched File Provider for a
dedicated dynamic configuration directory while retaining the existing Docker
Provider and ACME resolver.

#### Scenario: Traefik starts with an empty dynamic directory

- **WHEN** the File Provider is enabled before any tenant router is published
- **THEN** Traefik reads the mounted directory without adding a tenant route
- **AND** existing Docker-provider routes remain available

#### Scenario: Traefik receives the dynamic directory

- **WHEN** Compose starts the Traefik service
- **THEN** the host-side dynamic directory is mounted read-only at the configured provider path
- **AND** the existing Docker socket remains read-only
- **AND** the existing ACME storage and TLS-ALPN resolver remain unchanged

### Requirement: Dynamic tenant publication has a separate writer boundary

The deployment SHALL treat the host-side dynamic directory as an external
writer boundary and SHALL NOT grant Traefik or unrelated services write access
to it.

#### Scenario: Studio publishes a tenant router

- **WHEN** the separately authorized Studio provisioner atomically publishes a validated tenant file
- **THEN** Traefik can observe and load that file through its read-only mount
- **AND** no Docker-socket or ACME credential is delegated to Studio

