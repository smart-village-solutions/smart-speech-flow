# SSF Studio Control Plane Documentation Alignment

## Context

Smart Speech Flow (SSF) is deliberately prioritising a first Control Plane
foundation now. SVA Studio will administer SSF tenants and administrative
identities while SSF continues to own sessions and speech-AI runtime behaviour.
The existing documentation contains a broader, partially conflicting target
state. In particular, it grants regular cross-tenant user-management powers to
the root operator and does not define the plugin, identity, and trust boundaries
now selected.

## Goals

- Establish one canonical Studio-to-SSF Control Plane target architecture.
- Record the first delivery slice precisely without claiming implementation.
- Align product vision, roadmap, roles, and arc42 governance with the selected
  priority and security boundaries.
- Preserve the product priority of reliable sessions and simple standalone use.

## Non-Goals

- Implement Studio, SSF, Keycloak, database, API, or deployment changes.
- Specify normative API schemas, permissions, database tables, retry limits, or
  migration procedures; these belong to a later approved OpenSpec change.
- Bring later reporting, ClickHouse, support access, conversation-content, data
  export, or billing functionality into the first delivery slice.

## Decisions

### Canonical target document

`docs/architecture/sva-studio-control-plane.md` is replaced in full by the
approved Control Plane target text. It is the sole canonical description of
this architecture. It defines one Studio deployment within the deployment
boundary of one SSF installation; logical Studio instances represent SSF
tenants.

### Scope and ownership

Studio owns administrative governance: root authorisation, tenant lifecycle,
tenant-local IAM, audit, plugin activation, and provisioning workflows. The
SSF plugin owns SSF-specific configuration and data. SSF owns session and
speech-AI runtime data. Studio and SSF do not share a domain database and use
versioned internal APIs with explicit service identities.

### Identity and authorisation

Every tenant has a dedicated Keycloak realm. Root and tenant scopes remain
separate. A root operator creates tenants and initial tenant administrators but
does not perform regular cross-tenant user administration. A later support path
is separate, time-limited, explicitly authorised, and audited. Customers keep
their restricted SSF session access and do not become normal Studio identities.

### First delivery slice and roadmap position

The selected near-term scope is a Control Plane Foundation: generic
platform-bound plugin contributions and activation policies; tenant and
Keycloak provisioning; an initial tenant administrator; tenant-local IAM; a
plugin-owned PostgreSQL database and baseline record; minimal internal
configuration API; audit, reconciliation, and readiness.

This is an intentional prerequisite for real operator and tenant pilots, not a
decision to pull all Phase-4 operations forward. Quotas, reporting,
ClickHouse/session data, support access, conversation content, billing, and
full lifecycle/privacy processes remain later work. Roadmap phases 1 and 2
retain their priority for conversation reliability and standalone usability.

### Documentation updates

- Product vision names the Control Plane Foundation as a deliberately
  prioritised enabler and keeps SSF as runtime owner.
- Product roadmap adds the foundation before the broader Phase-4 operating
  maturity, with explicit scope limits.
- Roles and permissions adopts the root/tenant separation and records future
  support as an exception path.
- The arc42 index identifies the canonical target and the required later
  arc42/ADR/OpenSpec follow-up.

## Consistency Rules

- No document may imply that Studio and SSF share a domain database.
- No document may grant root users routine tenant-local user administration or
  ordinary access to conversation content.
- No document may describe first-slice functionality as already implemented.
- Roadmap language must distinguish the now-prioritised foundation from the
  wider Phase-4 operations scope.

## Verification

- Review the final diff for the stated document set.
- Search the affected documents for contradictory root-user-management and
  shared-database wording.
- Confirm that the first delivery scope consistently excludes reporting,
  ClickHouse/session data, support access, and conversation content.
