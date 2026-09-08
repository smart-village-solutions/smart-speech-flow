## Context

SSF will call Studio's internal Runtime Configuration V1 API. Developers need
a deterministic peer while Studio is unavailable or while reproducing error
handling. The mock must exercise the published HTTP contract, rather than
adding a shortcut inside SSF.

## Decisions

- The mock is a standalone FastAPI service at the exact V1 path.
- It reads no real credentials but models fixed service-token authentication
  and `ssf.runtime-configuration.read` authorization.
- `X-Studio-Tenant-Id` is the only tenant selector. The mock does not accept
  legacy tenant or Studio deployment headers.
- A request header selects one of four documented error scenarios only in the
  mock.
- Docker Compose publishes the mock as `http://127.0.0.1:8010` only through
  the explicitly selected `studio-mock` profile. It does not use Traefik or
  TLS because this is an internal test dependency.
- Production Compose services never depend on or route to the mock.

## Risks and Mitigations

- Contract drift: verify response schemas and error envelopes in tests.
- Contract drift: validate the mandatory V1 headers, V1 locale names, the
  seven stable error envelopes, and canonical revisions in tests.
- Accidental exposure: isolate the service behind an opt-in profile and bind
  it only to loopback.
