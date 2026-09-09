## Context

Studio Runtime Configuration V1 is a tenant-bound internal API. Token
acquisition is intentionally injected so this client remains independent of
the OAuth2 implementation and can be tested against deterministic transports.

## Goals / Non-Goals

- Goals: exact request contract, fail-closed schema and tenant checks, stable error handling.
- Non-Goals: token acquisition internals, user tokens, sessions, response caching.

## Decisions

- Model known V1 fields with strict Pydantic types and permit unknown optional fields.
- Keep the endpoint path constant and configure only the Studio base URL.
- Surface safe error codes and the server-provided retryability value without response bodies.

## Risks / Trade-offs

- Forward-compatible fields are retained but not interpreted until a later contract revision.
- Invalid success and error bodies fail closed, which can temporarily make configuration unavailable.
