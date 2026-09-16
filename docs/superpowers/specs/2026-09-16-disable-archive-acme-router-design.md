# Disable Archive ACME Router Design

## Context

Production Traefik requested certificates for `translate-archive.smart-village.solutions`,
which has no DNS record, and previously accepted local-only host configuration such as
`auth.localhost`. These requests create persistent errors and can consume Let's Encrypt
rate-limit capacity. The archive hostname is intentionally retired rather than repaired.

## Goals

- Retire the archive frontend from the canonical production Compose topology.
- Prevent a production deployment from applying a configuration that asks ACME to
  issue a certificate for a local-only or non-resolving hostname.
- Keep ordinary development Compose behaviour and the Studio tenant-router writer
  boundary unchanged.

## Non-Goals

- Do not create or modify public DNS records.
- Do not change the Studio provisioner, its retry policy, or its tenant lifecycle.
- Do not alter the Traefik Docker/File provider security boundaries or ACME storage.

## Design

The production Compose overlay will omit `frontend-archive`, so the archive router cannot
be rendered or cause ACME work in production. The root development Compose file retains
the service for local development.

The production deployment guard will inspect the rendered Compose configuration before
`up -d`. It will reject a TLS router using the `le` resolver when any `Host(...)` value is
local-only or cannot be resolved through the production host resolver. A failure is
actionable and leaves containers unchanged. The guard is deliberately applied to
Docker-provider configuration; Studio remains responsible for producing valid dynamic
tenant-router files.

## Verification

- Compose contract tests prove the archive frontend and archive host are absent from the
  production overlay while the development definition remains unaffected.
- Deployment-script tests prove local-only and unresolvable ACME hosts fail before
  `production_compose up -d`, while a resolving public host passes.
- The focused Traefik and production-script test suites remain green.

## Studio Boundary

No Studio code change is required by this change. Studio PR #1419 explicitly defines the
Kassel Traefik service, network, and port, and reports an empty Graphile queue after its
live validation. Production rollout must still run the existing post-deployment tenant
router, TLS, and readiness checks. If that readback finds a newly published invalid
dynamic router, the required Studio follow-up is: reject it before atomic publication
when its hostname is not a public canonical tenant host or when its service is not the
configured `sva-studio-ssf@docker`; persist a terminal error and test both failures.
