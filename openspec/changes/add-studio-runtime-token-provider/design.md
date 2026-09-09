## Context

Studio exposes an internal runtime endpoint protected by a short-lived Keycloak
service token. This change implements only token acquisition; consuming runtime
configuration remains a separate capability.

## Goals / Non-Goals

- Goals: bounded acquisition, in-memory reuse, early renewal, safe diagnostics.
- Non-Goals: Keycloak provisioning, secret deployment, runtime schema handling.

## Decisions

- Use an async provider with one lock so concurrent refreshes collapse into one request.
- Inject transport and clock dependencies for hermetic tests; use `aiohttp` in production.
- Expose stable error codes and retryability without copying provider response bodies.

## Risks / Trade-offs

- A process restart discards the cache. This is intentional and keeps tokens out of storage.
- Clock skew can invalidate near-expiry tokens. A configurable bounded renewal skew mitigates it.
