## Context

The SonarCloud backlog is concentrated in a small set of backend hotspot files, with additional frontend and Docker findings. The highest-risk items are security findings, blocker-level FastAPI typing issues, and reliability issues in async runtime paths.

## Goals / Non-Goals

- Goals:
  - Remove all open SonarCloud findings
  - Preserve existing runtime behavior wherever possible
  - Improve API documentation and typing where Sonar requires it
- Non-Goals:
  - Redesign the product API
  - Change deployment topology or container networking behavior

## Decisions

- Decision: Fix work will be tracked in a dedicated OpenSpec change instead of extending `fix-remaining-code-quality`.
- Decision: Security and blocker issues are handled before maintainability cleanup.
- Decision: User-controlled values will be removed from logs or reduced to safe metadata instead of partially redacting raw values.
- Decision: Local direct-start host binding will be made loopback-only, while Docker runtime bindings remain unchanged.

## Risks / Trade-offs

- Large hotspot refactors can introduce regressions.
  - Mitigation: run targeted regression tests after each wave and a full validation sweep before completion.
- Removing data from logs can reduce debugging detail.
  - Mitigation: retain safe operational metadata such as booleans, counts, and non-user-controlled state.

## Migration Plan

1. Land security/blocker fixes first.
2. Address runtime/reliability issues in async paths.
3. Finish maintainability cleanup in hotspot files.
4. Close frontend and Docker findings.
5. Re-run quality checks and SonarCloud scan.
