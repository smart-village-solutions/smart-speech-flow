## 1. Production definition

- [ ] 1.1 Inventory and record the known-good running image versions and
  required persistent mounts.
- [ ] 1.2 Create the canonical pinned production Compose definition.
- [ ] 1.3 Validate that the canonical definition does not introduce an
  implicit application-image upgrade.

## 2. Recovery automation

- [ ] 2.1 Add a production health-check script for platform, GPU, containers,
  and service endpoints.
- [ ] 2.2 Add a systemd recovery unit with Docker and NVIDIA ordering.
- [ ] 2.3 Verify controlled reboot recovery completes within five minutes.

## 3. Backup reliability

- [ ] 3.1 Replace incomplete daily backup coverage with all persistent data,
  native database backups, and TLS/configuration backup.
- [ ] 3.2 Add manifest-based backup integrity verification.
- [ ] 3.3 Configure daily, weekly, and monthly systemd timers and retention.
- [ ] 3.4 Add and document a monthly isolated restore drill.

## 4. Operations and migration

- [ ] 4.1 Document controlled OS and application update and rollback flows.
- [ ] 4.2 Install or verify the NVIDIA generic kernel-module metapackage.
- [ ] 4.3 Remove orphaned never-started containers after successful canonical
  recovery verification.
