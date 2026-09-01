# Keycloak Infrastructure Foundation Design

## Status and purpose

This design defines a standalone infrastructure pull request that makes
Keycloak reproducibly deployable with Smart Speech Flow (SSF). It deliberately
does not implement the Studio--SSF tenant and runtime-configuration contract.

Keycloak is a technical component of an SSF installation. Studio will later
provision tenant, identity, role, claim, and permission data through the
approved control-plane contract.

## Scope

The infrastructure pull request SHALL provide:

- a pinned, optimized Keycloak container image;
- a private, persistent PostgreSQL database dedicated to Keycloak;
- an internal Compose network boundary with no host ports for Keycloak,
  PostgreSQL, or the Keycloak management interface;
- public HTTPS access only through Traefik;
- a required non-secret `KEYCLOAK_HOSTNAME` configuration value;
- required bootstrap-administrator and database credentials sourced only from
  the ignored deployment environment file;
- readiness health checks, Compose contract tests, and an operator runbook;
- documented backup, verification, upgrade, and rollback procedures.

Production sets `KEYCLOAK_HOSTNAME=auth.kassel.smartspeechflow.de`. Local and
other deployments may set a different hostname without altering Compose files.

## Architecture

```text
Internet
  -> Traefik (TLS, public route for KEYCLOAK_HOSTNAME)
  -> Keycloak (internal port 8080)
  -> Keycloak PostgreSQL (private Compose network and persistent volume)
```

Keycloak starts only after PostgreSQL is healthy. The Keycloak management port
is used only by the container-local readiness probe and MUST NOT be published.
The PostgreSQL service has neither published ports nor Traefik labels.

The build image is pinned to Keycloak 26.7.2. Runtime configuration uses
Keycloak's PostgreSQL settings, forwarded proxy headers, HTTP internally behind
Traefik TLS termination, and enabled health endpoints.

## Configuration and secrets

The deployment environment supplies these required secret values:

- `KEYCLOAK_DB_NAME`
- `KEYCLOAK_DB_USER`
- `KEYCLOAK_DB_PASSWORD`
- `KEYCLOAK_BOOTSTRAP_ADMIN_USERNAME`
- `KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD`

The PR documents their generation and restrictive environment-file permissions.
It MUST NOT add real credentials, users, client secrets, or application tokens
to the repository.

## Explicit exclusions

This PR MUST NOT introduce:

- a Keycloak realm import or application client configuration;
- SSF user roles, tenant claims, `ssf_permissions`, or a service account;
- Studio-driven provisioning or tenant lifecycle integration;
- gateway authorization or frontend login behaviour;
- a Node toolchain migration.

Those changes require a separate, approved OpenSpec aligned with the
Studio--SSF Runtime Configuration Contract V1 and SSF issue #266.

## Tests and rollout

Compose contract tests render the topology with throwaway credentials and verify
that Keycloak is publicly reachable only through Traefik, that the hostname is
configured through `KEYCLOAK_HOSTNAME`, that PostgreSQL is private and
persistent, and that required health checks and credentials are present.

The runbook requires DNS and TLS readiness, local generation of the required
secrets, build and startup commands, a private-database verification, a public
readiness check, and a tested encrypted logical-backup/restore procedure.

Rolling out this PR makes Keycloak operationally available only. It does not
enable SSF user authentication and does not modify the existing conversation
flow.
