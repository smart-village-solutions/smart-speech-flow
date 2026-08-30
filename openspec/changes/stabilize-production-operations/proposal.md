# Change: Stabilize production operations

## Why

Production recovery currently depends on multiple Compose definitions, mutable
image references, and incomplete backup verification. This creates operational
drift and makes reboots and routine updates unnecessarily risky.

## What Changes

- Establish one versioned, pinned production Compose definition.
- Add systemd-managed reboot recovery and a five-minute health verification.
- Make daily local backups complete, verifiable, and subject to defined
  retention and restore drills.
- Define controlled operating-system and application update rollback steps.
- Keep a matching NVIDIA kernel-module metapackage installed for future kernel
  updates.

## Impact

- Affected specs: `production-operations` (new capability)
- Affected code and configuration: Docker Compose, backup scripts, systemd
  units and timers, operations documentation, and monitoring integration.
- **BREAKING:** Production deployment and reboot recovery will use a canonical
  Compose definition instead of the currently fragmented runtime sources.
