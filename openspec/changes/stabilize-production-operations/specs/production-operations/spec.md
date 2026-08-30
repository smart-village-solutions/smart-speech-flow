## ADDED Requirements

### Requirement: Canonical production deployment definition

The system SHALL maintain one versioned production Compose definition that
describes every production service and pins every application image to a fixed
version or immutable digest.

#### Scenario: Validate production configuration

- **WHEN** an operator validates the canonical production Compose definition
- **THEN** configuration validation succeeds without downloading or replacing
  production containers

#### Scenario: Prevent implicit image upgrade

- **WHEN** production recovery runs after a reboot
- **THEN** it starts only the image versions declared by the canonical
  production definition

### Requirement: Automated reboot recovery

The system SHALL automatically start the canonical production workload after a
host reboot and SHALL verify recovery within five minutes.

#### Scenario: Successful reboot recovery

- **WHEN** the host reboots with Docker and the NVIDIA driver available
- **THEN** every required production service starts and the health verification
  succeeds within five minutes

#### Scenario: GPU recovery failure

- **WHEN** the NVIDIA driver is unavailable after reboot
- **THEN** the recovery health verification fails and records the GPU failure
  in the system journal

### Requirement: Verified local backups

The system SHALL create at least one verified complete local backup every 24
hours and retain seven daily, four weekly, and twelve monthly backups.

#### Scenario: Complete daily backup

- **WHEN** the daily backup timer runs
- **THEN** it includes expected persistent data, configuration, and TLS
  material and verifies every created archive against its manifest

#### Scenario: Backup failure

- **WHEN** an expected backup artifact is missing or unreadable
- **THEN** the backup job fails and records the failure in the system journal

### Requirement: Controlled updates and rollback

The system SHALL require an upgrade simulation and a fresh verified backup
before operating-system updates and SHALL provide a versioned rollback path for
application deployments.

#### Scenario: Operating-system update validation

- **WHEN** an operator applies operating-system updates
- **THEN** the system performs the post-reboot health verification before the
  update is accepted as successful

#### Scenario: Application deployment failure

- **WHEN** a pinned application deployment fails health verification
- **THEN** the operator can restore the previous versioned Compose definition
  and image set and rerun health verification
