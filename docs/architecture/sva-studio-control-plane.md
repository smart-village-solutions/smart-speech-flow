# SSF Control Plane in SVA Studio: Target Architecture

## Status and Purpose

This document records the agreed architectural foundation for using SVA Studio
as the administrative Control Plane of a Smart Speech Flow (SSF) installation.
It describes a target architecture, not an implemented or deployed state. A
separate OpenSpec change will provide the normative specification later.

The first delivery slice covers tenant and user creation and management.
ClickHouse analytics, a separate session database, conversation content, and
support access are explicitly outside this initial scope.

## Deployment and Tenant Model

One Studio deployment runs with exactly one SSF installation in the same server
or deployment boundary. One logical Studio instance represents exactly one SSF
tenant.

\`\`\`text
SSF server or deployment
├── Smart Speech Flow
├── SSF Keycloak
├── SVA Studio
└── PostgreSQL database of the SSF plugin
\`\`\`

The shared deployment boundary does not remove system boundaries. Studio and
SSF have no shared domain database and do not access each other's persistence
directly. They integrate through versioned internal APIs and explicit
technical identities.

## Role Mapping

SSF business roles and Studio technical roles remain distinct:

| SSF business role | Technical Studio mapping |
| --- | --- |
| \`system_admin\` | Root scope with \`instance_registry_admin\` |
| \`tenant_admin\` | Tenant-local Studio \`system_admin\` in the realm of the Studio instance |
| \`admin\` | Tenant-local user with selected \`ssf.*\` permissions |
| \`customer\` | No regular Studio identity; access through a restricted SSF session |

The root system administrator creates a tenant and its initial tenant
administrator. The tenant administrator then manages users and roles in its
own tenant. Routine cross-tenant user administration by the root system
administrator is not part of this target architecture. A future support or
recovery path must be separate, time-limited, and fully audited.

## Core and Plugin Responsibilities

SSF domain logic stays entirely outside the Studio Core. The Core gains only
generic plugin capabilities that can serve other plugins as well.

| Layer | Studio Core | SSF plugin |
| --- | --- | --- |
| Root | Plugin catalogue, instance lifecycle, root authorisation, Keycloak provisioning, initial tenant administrator, secrets, jobs, and audit | SSF root navigation, tenant status, installation-wide SSF configuration, and SSF-specific root actions |
| Tenant | Authentication, IAM, users, roles, groups, effective permissions, and module activation | SSF configuration, \`ssf.*\` permissions, tenant UI, and internal SSF domain contracts |
| Persistence | Studio governance: instances, IAM, audit, and plugin activation state | One tenant-aware PostgreSQL database for installation-wide and tenant-specific SSF data |
| Runtime | Host-managed authentication, authorisation, error contracts, audit, and job execution | SSF handlers, validation, repositories, and calls to internal SSF APIs |

The plugin contract must generically support platform-bound routes, navigation,
actions, and server-side contributions. A plugin must not reinterpret a
platform role as a tenant-local permission; root and tenant access remain
separate authorisation paths.

## Installation and Activation Policies

The Studio installation determines which plugins are included in a deployment.
A Studio is SSF-capable when the SSF plugin is in the installed,
host-validated plugin catalogue. The Core requires no SSF-specific operating
mode such as \`isSsfStudio\`.

The generic plugin contract defines three tenant activation policies:

| Policy | Initial state | Manually deactivatable |
| --- | --- | :---: |
| \`optional\` | disabled | Yes |
| \`automatic\` | enabled | Yes |
| \`required\` | enabled | No |

The SSF plugin initially uses \`automatic\`. Manual deactivation of an
automatically activated plugin is a persistent desired state and must not be
reversed by restart or reconciliation.

When a plugin is installed later:

- \`optional\` remains disabled initially for existing and new tenants.
- \`automatic\` is activated for existing tenants through a controlled,
  audited reconciliation and directly for new tenants.
- \`required\` is activated for every existing and new tenant. Installation is
  ready only after reconciliation succeeds.

A required plugin remains technically a plugin, not a Core component. Tenant
and root APIs reject its deactivation server-side. Removing it from a
deployment is a separate operational procedure and does not automatically
delete plugin data or history.

## Keycloak and Identity Model

Studio and SSF use the dedicated Keycloak of the SSF server. Realm boundaries
represent organisational tenant boundaries:

\`\`\`text
SSF Keycloak
├── Root realm
│   └── System administrators
├── Tenant realm A
│   ├── Tenant administrators
│   └── Operational administrators
└── Tenant realm B
    ├── Tenant administrators
    └── Operational administrators
\`\`\`

Each tenant receives its own realm. A user belongs to exactly one tenant. The
same natural person needs separate identities for two tenants; matching email
addresses do not create automatic account linking.

Studio and SSF use separate OIDC clients and audiences. Root users are not
copied into tenant realms. Customers with SSF session tokens remain outside
Studio IAM.

## SSF Plugin Database

The SSF plugin owns one PostgreSQL database per SSF installation. It contains
both installation-wide and tenant-specific configuration. The Studio Core
knows no SSF tables or domain fields.

Tenant records use the canonical Studio \`instanceId\` as their tenant key.
Tenant access is bound server-side to this context and secured with row-level
security. Root access follows a separate, explicitly authorised database path.
Migrations, repositories, and schema ownership belong to the SSF plugin.

The database can later contain installation-wide model, integration, and
default configuration; tenant branding, texts, languages, options, quotas,
configuration revisions, and SSF readiness and synchronisation state.

Binary media must not be duplicated. The plugin stores references to existing
Studio media management and returns only authorised, suitable delivery
references to SSF.

## Internal API Between SSF and Studio

SSF determines the tenant from a valid session token or Keycloak login. The SSF
backend then calls the internal Studio API with its own service identity and a
short-lived signed tenant assertion. A freely supplied \`instanceId\` is not a
trust boundary.

The Studio host validates the technical identity, audience, validity,
replay protection, and tenant binding before invoking the SSF plugin handler in
the bound tenant context. Browsers receive neither database credentials nor
direct access to this internal API.

## First Delivery Runtime Flows

### Create a tenant

\`\`\`text
Root system administrator creates a Studio instance
    → Core provisions tenant realm and separate OIDC clients
    → Core creates the initial tenant administrator
    → Core activates the installed automatic SSF plugin
    → Core materialises tenant-local SSF IAM baseline
    → SSF plugin creates tenant baseline data
    → Readiness checks confirm realm, clients, IAM, and plugin data
    → Tenant is reported usable
\`\`\`

Every step has persistent, diagnosable status. Retries reconcile the same
desired state and create neither a second realm nor a second SSF tenant record.
Partly configured tenants remain fail-closed.

### Manage users

After successful creation, the tenant administrator manages users and roles in
the existing tenant-local Studio IAM UI. Every mutation is authorised against
the active instance context and executed only in its tenant realm. Root rights
do not grant tenant-local rights, and tenant roles grant no root rights.

### Deactivate and reactivate the SSF plugin

For an \`automatic\` plugin, the root system administrator may manually remove
a tenant's activation. This blocks tenant SSF routes and internal SSF
configuration access. Persisted configuration and audit records remain. A later
reactivation reconciles schema, IAM baseline, and tenant baseline data before
the status becomes \`ready\` again.

## Scope and Later Stages

### First delivery slice

- Generic platform-bound plugin contributions.
- \`optional\`, \`automatic\`, and \`required\` activation policies.
- Installation and automatic tenant activation of the SSF plugin.
- Root and tenant realm provisioning in the existing SSF Keycloak.
- Initial tenant administrator.
- Tenant creation, suspension, and reactivation.
- Tenant-local user and role management.
- SSF plugin database and tenant baseline record.
- Minimal internal SSF configuration API.
- Audit, reconciliation, and readiness.

### Later stages

- Complete branding, text, model, and option administration.
- ClickHouse and session-data analytics.
- Usage, cost, and capacity reporting.
- Controlled support access.
- Conversation-content display where approved for business and data-protection
  purposes.

SSF remains authoritative for ClickHouse, session data, and conversation
content. Studio will consume those data later through an internal SSF
administration or reporting API rather than accessing SSF runtime databases
directly.

## Security and Quality Boundaries

- Authentication, tenant resolution, and authorisation are enforced server-side.
- Root and tenant scopes remain separate in UI, API, Keycloak, and database.
- Plugin and service secrets never reach browser responses, logs, or audit
  payloads.
- Provisioning, reconciliation, and internal mutations are idempotent and
  auditable.
- Error states expose no partially configured domain access.
- Plugin deactivation never deletes data automatically.
- Conversation content is outside the first delivery slice.

## To Define in the Later OpenSpec Change

The normative specification must define API schemas, permission IDs, database
tables, readiness states, retry limits, token lifetimes, and the migration path
for existing Studio instances. It must also update arc42 sections 03–08, 10,
and 11 and record an ADR for the realm, plugin, and trust-boundary decisions.
