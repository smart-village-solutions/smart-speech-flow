# Change: Rebase API Gateway Boundary Refactor

## Why

The existing boundary-refactor plan predates delivered tenant isolation, Studio runtime integration, fail-closed persistence, pipeline admission, live resilience, feedback persistence, and quality telemetry. Its current task list has no completed items and no longer describes the gateway that implementation must preserve.

Without a rebase, #228 risks undoing current tenant/runtime behavior or duplicating delivered work while trying to establish maintainable boundaries.

## What Changes

- Rebase the existing `refactor-api-gateway-boundaries` execution plan on the current tenant-aware gateway.
- Treat `TenantSessionKey`, tenant-scoped persistence, Studio runtime resolution, fail-closed persistence, pipeline admission, live resilience, feedback, telemetry, and existing lifespan-owned state as baseline constraints.
- Sequence implementation into characterization/composition root, session/message/pipeline, realtime/polling/monitoring, and compatibility-cleanup slices.
- Require a recorded decision before deleting or isolating the legacy session path.
- Preserve public REST, WebSocket, polling, OpenAPI, Redis-session, and pipeline-metadata contracts throughout all slices.

## Impact

- Affected capability: `api-gateway-modular-architecture`
- Affected artifacts: this change's proposal, design, tasks, and spec delta; subsequent work affects `services/api_gateway`, tests, and architecture docs.
- Compatibility: no intentional public or deployment behavior change in this planning rebase.
- Coordination: #347 provides the first detailed structural slice. #227, #225, and #348 retain their own scopes.

## Non-Goals

- Implementing the refactor in this PR.
- Changing authorization, tenant identity, session lifecycle, rate limits, or public endpoint behavior.
- Adding distributed realtime or multi-replica behavior (#227).
- Extracting transport-free AI service cores (#225).
