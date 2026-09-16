## Context

The production overlay currently includes a retired archive frontend with an ACME-enabled
host that does not resolve. The deployment guard validates only the Keycloak hostname and
Studio runtime environment variables.

## Decisions

- Retire, rather than repair, the archive production route.
- Validate ACME router hosts from the rendered production Compose configuration before
  container reconciliation.
- Treat local-only and DNS-unresolvable hosts as deployment failures.
- Leave Studio's external dynamic-router writer unchanged; it has its own validation and
  live-readback boundary.

## Risks and Mitigation

- DNS lookup can fail transiently during deployment. The guard fails closed before a
  configuration change, producing the hostname in its actionable error output.
- A retired archive consumer loses its route. This is the explicitly approved outcome;
  development Compose remains available for local archive work.

## Rollback

Restore the removed production service only after its public DNS record is available and
the guarded deployment check succeeds.
