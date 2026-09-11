# Tenant Isolation Production Cutover

This runbook performs the approved hard cut from unscoped conversation state
to tenant-isolated v2 state. The production installation is assumed to have no
users and no conversation data that must be retained. The reset is destructive
and intentionally has no data-restore path.

## Preconditions

- The reviewed gateway and frontend commits have been built as immutable
  `prod-<git-sha>` images and those exact tags are set in the production Compose
  file.
- `SSF_ENABLE_LEGACY_ADMIN_ACCESS=false` is effective.
- The reconnect grace, warning, and maximum-lifetime settings are respectively
  `30`, `5`, and `8`.
- ClickHouse migration `005_tenant_reference.sql` has been applied before
  quality telemetry is enabled.
- Studio returns at least two production tenants, and each corresponding
  Keycloak realm issues a token containing the correct `studio_tenant_id`,
  audience, and required role.
- The two test tokens are held only in shell environment variables and are not
  pasted into commands, logs, tickets, or chat.

## Cutover

1. Record the previous immutable gateway and frontend image tags for rollback.
2. Validate the Studio directory and Keycloak claims for both test tenants.
3. From the repository root, load the production Compose helper and stop only
   the public conversation workloads:

   ```bash
   source scripts/lib/production-common.sh
   production_compose stop api_gateway frontend
   ```

4. Confirm that neither workload is running:

   ```bash
   production_compose ps --status running --services
   ```

   `api_gateway` and `frontend` must not appear. Redis remains running so the
   one-off cutover container can remove the allowlisted keys.

5. Preview the guarded reset from the repository root:

   ```bash
   scripts/reset-legacy-conversation-state.sh --dry-run
   ```

   Record and review the reported Redis-key and audio-directory match counts.
   Stop if they differ from the expected empty-production legacy state.

6. Apply the reviewed reset:

   ```bash
   scripts/reset-legacy-conversation-state.sh --destructive-reset-production
   ```

   The command deletes only `ssf:sessions`, `ssf:session:*`, and the legacy
   `/data/audio/original` and `/data/audio/translated` directories. It excludes
   `ssf:v2:*`, uses Redis `UNLINK`, prints counts rather than identifiers, and
   is safe to repeat.

7. Start the reviewed v2 images:

   ```bash
   production_compose up -d api_gateway frontend
   ```

8. Run the production health check and the credential-safe two-tenant smoke
   test described in the tenant-isolation release commit. Verify that each
   tenant can complete its own flow and receives the same neutral `404` for the
   other tenant's sessions.

## Rollback

1. Stop `api_gateway` and `frontend`.
2. Restore the previously recorded immutable image tags.
3. Start `api_gateway` and `frontend`, then run the production health check.

Rollback restores code and images only. The deleted legacy conversations and
audio are not restored; both forward deployment and rollback start without
conversation state.
