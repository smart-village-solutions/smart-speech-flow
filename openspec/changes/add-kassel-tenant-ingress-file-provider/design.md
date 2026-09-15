# Design: Kassel tenant ingress file provider

## Context

Traefik already uses the Docker provider and TLS-ALPN ACME. Kassel has wildcard
DNS but no DNS-01 credentials. Tenant routers must therefore remain explicit
and request certificates through the existing resolver.

## Decisions

- Traefik watches `/etc/traefik/dynamic` via the file provider.
- Root Compose bind-mounts `./traefik/dynamic`; canonical production Compose
  resolves the same repository directory as `../../traefik/dynamic`. Both
  mounts expose it read-only at `/etc/traefik/dynamic`.
- The directory is empty by default, so enabling it does not alter existing
  routing.
- The external Studio provisioner owns atomic publication into the host-side
  directory. Traefik never receives write access.
- Existing Docker labels and the `le` resolver remain authoritative for all
  existing routes until hosts are migrated individually.

## Security boundary

The File Provider is a configuration reader, not an API. This change adds no
socket, credential, or public endpoint. Tenant filenames and contents are
validated and atomically published by Studio under its separately reviewed
contract.

## Rollout

Enable the provider with an empty directory first and verify all existing
routes. Studio may publish a higher-priority explicit tenant router only after
that baseline succeeds. Static hosts are removed individually after external
TLS and login acceptance.

## Rollback

Stop the Studio writer, restore the explicit Docker-label host where needed,
verify it externally, and only then remove the corresponding dynamic file.
Disabling the File Provider must not alter the Docker provider or ACME store.
The production backup retains `traefik/dynamic`, so a host restore also
recovers the explicit tenant router files.
