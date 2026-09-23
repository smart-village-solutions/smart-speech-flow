## Context

The gateway is currently tenant-aware. It has `TenantSessionKey`, a tenant Redis session store, Studio runtime resolution, a fail-closed runtime policy, consent-gated persistence, admission control, live resilience, feedback services, and telemetry. Several collaborators already live on `app.state` and are constructed in FastAPI lifespan.

The same gateway retains global `session_manager`, `conversation_service`, and `realtime_ticket_store` instances, zero-argument `lru_cache` factories, and route-to-service imports. `SessionManager` retains legacy and tenant modes. Thus, the old architecture proposal is correct in direction but stale as an execution baseline.

## Goals / Non-Goals

### Goals

- Preserve delivered tenant, runtime, privacy, resilience, admission, feedback, and telemetry behavior.
- Move production collaborator ownership to one lifespan-owned dependency container and FastAPI providers.
- Split session/message/pipeline and realtime/polling/monitoring responsibilities behind typed boundaries.
- Characterize compatibility before each migration slice and clean up compatibility facades only after callers move.

### Non-Goals

- Change external REST, WebSocket, polling, OpenAPI, Redis, or pipeline-metadata contracts.
- Change tenant or authorization semantics.
- Add Redis Pub/Sub or multi-replica behavior (#227).
- Refactor AI service internals (#225).
- Delete legacy state without an approved and evidence-backed cutover decision.

## Decisions

### Decision: Current behavior is the characterization baseline

All migration slices first characterize the present admin/customer tenant flows, Studio runtime failures, consent/persistence gates, pipeline metadata, realtime tickets, polling, and lifespan shutdown. Existing public semantics control when an old plan statement conflicts with implemented behavior.

### Decision: Lifespan-owned composition root

`GatewayDependencies` holds all request-facing collaborators, created in `lifespan` and stored in `app.state`. Providers retrieve explicit collaborators; test overrides replace providers. New production code must not instantiate or replace module globals, or use zero-argument cached factories for injectable services.

Existing app-state services migrate into the container without behavioral changes. Global objects remain temporary adapters until consumers are migrated.

### Decision: Preserve tenant-aware state

Session and message boundaries preserve `TenantSessionKey`, tenant Redis keys and join index, consent-gated storage, runtime snapshots, and pipeline metadata. The session compatibility gate records whether legacy mode can be deleted after cutover proof or must be isolated behind a typed adapter. No code slice assumes legacy state is absent merely because the target architecture does.

### Decision: Separate transport responsibilities

Route adapters call application services; application services depend on typed ports. Speech HTTP access, validation/conversion/storage are infrastructure adapters. The realtime ticket backend exposes `consume`, `put_if_absent`, and `get` domain operations rather than Redis eval details. Realtime registry, dispatch, heartbeat, polling, and monitoring have focused interfaces. #348 decides the supported tenant-safe monitoring API surface.

### Decision: Four delivery slices

1. Characterization and composition root.
2. Session/message/pipeline boundaries.
3. Realtime/polling/monitoring boundaries.
4. First-party migration, compatibility cleanup, and verification.

Each slice must be independently releasable and preserve public contract behavior.

## Risks / Trade-offs

- Contract drift: characterize public contracts before migrations and require API and realtime tests per slice.
- Tenant privacy regression: include tenant-isolation and cross-tenant negative tests in every affected slice.
- Legacy cleanup error: require a hard decision gate and explicit consumer inventory.
- Global-to-provider migration test fragility: override dependency providers and use test app instances rather than mutating module state.
- Competing scopes: explicitly exclude #225, #227, and #348.

## Migration Plan

1. Rebase planning artifacts only in this PR; do not change runtime code.
2. Implement phase 1 only after approved tasks and a characterized baseline.
3. Implement later phases in focused PRs that reference #228 and the phase.
4. Remove facades only after full compatibility verification.

## Rollback Plan

This PR changes no runtime code. A later implementation slice rolls back only that slice while preserving the characterization tests.
