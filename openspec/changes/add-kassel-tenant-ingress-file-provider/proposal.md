# Change: Add the Kassel tenant ingress file provider

## Why

Kassel tenant hosts currently require manual edits to the Studio container's
Traefik labels. Studio needs a narrow, durable configuration boundary that can
publish one explicit router per provisioned tenant without receiving Docker or
ACME access.

## What Changes

- Enable Traefik's watched file provider for a dedicated dynamic directory.
- Mount that directory read-only into Traefik.
- Keep the Docker provider, TLS-ALPN resolver, existing routers, and ACME store
  unchanged.
- Define the cross-repository writer contract used by the standalone Studio
  provisioner; this repository does not write tenant router files itself.

## Impact

- Affected capability: `tenant-ingress`
- Affected code: `docker-compose.yml`, production Compose validation
- External consumer: the Kassel standalone deployment of `sva-studio`

