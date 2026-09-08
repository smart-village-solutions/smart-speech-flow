## Context

SSF will call Studio's internal Runtime Configuration V1 API. Developers need
a deterministic peer while Studio is unavailable or while reproducing error
handling. The mock must exercise the published HTTP contract, rather than
adding a shortcut inside SSF.

## Decisions

- The mock is a standalone FastAPI service at the exact V1 path.
- It reads no real credentials and deliberately accepts unauthenticated
  requests because it serves only fixed, non-sensitive test data.
- A request header selects a documented error scenario only in the mock.
- Docker Compose publishes the mock as `http://<host-ip>:8010` only through
  the explicitly selected `studio-mock` profile. It does not use Traefik or
  TLS because this is a temporary test dependency.
- Production Compose services never depend on or route to the mock. Operators
  who enable the profile accept that its HTTP port is externally reachable.

## Risks and Mitigations

- Contract drift: verify response schemas and error envelopes in tests.
- Misuse as a production dependency: the endpoint is intentionally
  unauthenticated and unencrypted, so it remains isolated behind an explicit
  profile and contains only fixed test data.
- Accidental exposure: isolate the service behind an opt-in profile and
  document that the port binds to all interfaces.
