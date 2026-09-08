## Context

SSF will call Studio's internal Runtime Configuration V1 API. Developers need
a deterministic peer while Studio is unavailable or while reproducing error
handling. The mock must exercise the published HTTP contract, rather than
adding a shortcut inside SSF.

## Decisions

- The mock is a standalone FastAPI service at the exact V1 path.
- It reads no real credentials and accepts only documented test bearer tokens.
- A request header selects a documented error scenario only in the mock.
- Docker Compose exposes it only through the `studio-mock` profile.
- Production Compose services never depend on, route to, or enable the mock.

## Risks and Mitigations

- Contract drift: verify response schemas and error envelopes in tests.
- Accidental production use: isolate the service behind an opt-in profile and
  use a distinct local URL.
