# Studio--SSF Runtime Configuration Contract V1

## Status and purpose

This is the implementation-ready revision of the Studio--SSF runtime
configuration contract. It replaces the previous draft before either system
implements the interface. The API major version and schema value remain V1
and `1.0` respectively.

The contract covers a Studio installation that operates several tenants and
the matching multi-tenant SSF installation. It defines the configuration read
API and the SSF rules needed to apply it safely. Analytics, billing, support
access, ClickHouse, Studio user lists, and an SSF tenant-administration UI are
out of scope.

## Terms and ownership

- `studio_instance_id` identifies a Studio installation. It is contextual
  metadata and MUST NOT be used as an SSF data-access boundary.
- `tenant_id` identifies one stable Studio tenant and exactly one SSF tenant.
  It is the canonical tenant identifier for this contract.
- Studio Core owns tenant records, tenant lifecycle, Keycloak provisioning,
  user accounts, policies, media, configuration, readiness, and audit.
- The Studio SSF plugin owns resolution of server-wide, tenant-specific, and
  product-default configuration values.
- SSF owns authentication enforcement, guest sessions, conversation flow,
  and SSF runtime/session/conversation data.

Studio and SSF MUST NOT share an application database or access each other's
persistence directly. SSF MUST NOT persist a Studio runtime-configuration
response.

## Identities and authorization

Each regular SSF account belongs to exactly one tenant. Each login produces a
token for exactly that tenant; people requiring access to several tenants use
separate accounts and log in separately. A tenant-user token contains at least
the following signed claims in addition to standard OIDC claims:

```json
{
  "sub": "keycloak-user-id",
  "studio_instance_id": "01J...",
  "tenant_id": "01J...",
  "ssf_roles": ["user"],
  "ssf_permissions": ["ssf.sessions.create"],
  "preferred_username": "erika",
  "name": "Erika Muster",
  "locale": "de-DE"
}
```

`ssf_permissions` are authoritative for server-side authorization.
`ssf_roles` are for classification, navigation, and audit. The initial
operational permission catalogue is:

- `ssf.sessions.create`
- `ssf.sessions.read`
- `ssf.sessions.terminate`
- `ssf.conversations.participate`

The token roles are `system_admin`, `tenant_admin`, and `user`. A
`tenant_admin` has no operational SSF conversation permissions unless it also
has `user` and the corresponding permissions. A `system_admin` has no
`tenant_id` and MUST NOT access tenant conversations or tenant data; tenant
configuration and inspection remain Studio responsibilities.

Guests receive neither a Studio account nor a regular Keycloak token. The
existing SSF participant values `admin` and `customer` remain protocol values
during the migration and are not token roles. Their internal renaming is a
separate SSF change.

## Tenant context and guest sessions

SSF MUST derive `tenant_id` from a validated user token for every authenticated
tenant operation. When a user creates a session, SSF MUST bind that tenant ID
to the session permanently.

Guests join without logging in. SSF issues both an eight-character, human-
usable session code and a high-entropy, session-scoped join token embedded in
the QR-code URL. Either is a full guest-join path. Resolving either credential
MUST derive the tenant and session only from SSF server-side state; browsers
MUST NOT submit or select a tenant. The short-code path MUST use
cryptographically random codes, short session validity, rate limiting, and
generic failure responses.

Every SSF persisted data object and Redis key/path MUST be tenant-bound. Every
resource lookup MUST additionally compare the tenant derived from the token or
guest join credential with the tenant recorded for the resource. Missing or
conflicting context MUST fail closed.

## Runtime configuration API

```http
GET /internal/plugins/ssf/v1/runtime-configuration
Authorization: Bearer <service-token>
X-Tenant-Id: <tenant-id-derived-by-SSF>
X-Correlation-Id: <correlation-id>
```

The endpoint is internal-network only and is callable only by the SSF backend.
SSF uses a dedicated Keycloak client with Client Credentials. Its token MUST
carry the configured audience and `ssf.runtime-configuration.read`. It is
separate from browser and user clients. Studio treats `X-Tenant-Id` as a
statement by the authenticated SSF backend. V1 requires neither a second
tenant assertion, replay storage, nor mTLS.

The successful response contains `contractVersion: "1.0"`,
`configurationRevision`, tenant ID/display name/time zone, optional logo and
icon, enabled BCP-47 languages and their texts, and the effective conversation
storage policy. Studio returns fully resolved values only; policy origins and
administrative fields are not exposed. The response MUST echo the requested
tenant ID in `tenant.id`.

```json
{
  "contractVersion": "1.0",
  "configurationRevision": "sha256:...",
  "tenant": {
    "id": "01J...",
    "displayName": "Example Municipality",
    "timeZone": "Europe/Berlin"
  },
  "branding": {
    "logo": { "url": "https://example.org/logo.png", "alternativeText": "Logo" },
    "icon": { "url": "https://example.org/icon.png", "alternativeText": "Icon" }
  },
  "localization": {
    "defaultLanguage": "de-DE",
    "languages": [{
      "language": "de-DE",
      "authenticatedHomeExplanationHtml": "<p>...</p>",
      "guestExplanationHtml": "<p>...</p>",
      "conversationContentStorageQuestionHtml": "<p>...</p>"
    }]
  },
  "conversationContentStorage": { "mode": "ask" }
}
```

`branding.logo` and `branding.icon` MAY each be `null`. If the effective
storage mode is `disabled`, `conversationContentStorageQuestionHtml` MUST be
`null` for every language.

`configurationRevision` is `sha256:` followed by SHA-256 over the RFC 8785
JSON Canonicalization Scheme representation of the fully resolved configuration
excluding `configurationRevision` itself.

The effective value of every field and language is resolved independently:

```text
tenant customization
  ?? server-wide customization
  ?? product default shipped with the relevant software version
```

## Runtime use and tenant availability

SSF MUST read runtime configuration when it renders an authenticated or guest
entry page and when it starts a session. It MUST re-read the current storage
policy before every operation that would persist conversation content. SSF MAY
keep the configuration already delivered to a browser as a presentation
snapshot for the current active session, but MUST NOT persist it.

Studio returns `409` when a tenant is inactive, suspended, the plugin is
inactive, or the tenant is not ready. SSF MUST then neither start a session nor
accept persistent conversation processing for that tenant. If runtime
configuration is unavailable at a policy check, SSF MUST fail closed for
persistence. An already active conversation MAY continue with transient
processing only.

## Languages, texts, and branding

All external language values in this contract MUST use BCP-47 language tags,
including enabled languages, default language, text variants, session language
selection, and SSF API data. SSF displays only the enabled languages from
Studio. Mapping a BCP-47 value to an ASR, translation, or TTS provider code is
an SSF-internal implementation detail. V1 does not require server-side denial
of a pipeline language code that is called outside the UI.

For every enabled language Studio returns the authenticated-home explanation,
guest explanation, and, when applicable, conversation-storage question. The
default language MUST be enabled. At least one language MUST remain enabled.
Existing tenant overrides MAY remain stored while their language is disabled.

Studio is the security boundary for these HTML fields and MUST sanitize active
or executable content, event handlers, and dangerous URL schemes. In V1 SSF
may render the Studio-provided HTML as trusted content; independent SSF
sanitization is deferred hardening. Branding logo and icon are optional and
may be `null`.

## Studio policy and write boundary

Studio system administrators manage `customBrandingAllowed` and
`conversationContentStorageAllowed` for every tenant, as well as server-wide
values. Tenant administrators manage enabled languages, default language,
individual text overrides, their desired storage mode, and branding only when
custom branding is permitted. Users and guests cannot change configuration.

If custom branding is withdrawn, the tenant's stored branding selection remains
stored but is no longer effective. If conversation-content storage is not
allowed, the effective mode returned to SSF is always `disabled`; a tenant's
different stored selection has no effect. A successful Studio change is active
immediately: ordinary branding, text, and language changes appear on the next
entry-page load or new session, while tenant availability and the effective
storage prohibition apply to subsequent protected operations.

## Conversation content and consent

The effective storage mode is `ask` or `disabled`. With `ask`, SSF presents the
localized question to the guest before activating the session. The guest's
choice is stored only as a minimal, content-free session consent status.

If the guest declines, the conversation MAY proceed, but SSF MUST process
content only transiently for the live translation. It MUST NOT persist audio,
messages, transcripts, translations, or other derived conversation content.
`disabled` has the same no-persistence behaviour but does not ask the guest;
the tenant policy determines it. Thus `disabled` does not prohibit the
transient processing strictly necessary to provide the live conversation.

Content covered by this prohibition MUST NOT be persisted indirectly in SSF
logs, error details, or audit records. SSF's broader internal logging policy
is outside this integration contract.

## Errors, audit, and evolution

Runtime errors use the stable `contractVersion` and `error` envelope with a
machine-readable `code`, generic `message`, boolean `retryable`, and
`correlationId`. `401` and `403` apply to the service client, `404` to an
unknown tenant, `409` to unavailable tenant states, and `503` to temporary
runtime-configuration unavailability. Responses MUST NOT disclose secrets,
internal persistence details, or data of another tenant.

Studio durably audits configuration and policy changes. Normal runtime reads
produce only technical metrics and structured logs. `X-Correlation-Id` links
diagnostics between Studio and SSF.

The API major version is in the path. Backward-compatible optional fields MAY
be added within V1. SSF MUST ignore unknown fields and strictly validate known
ones. A new required field, a removed field, or changed semantics requires a
new major version. Studio and SSF MUST support at least one common major
version during a transition.

## Acceptance criteria for the accompanying OpenSpec work

- Tokens, sessions, Redis paths, resource lookups, and WebSockets prove tenant
  isolation with positive and cross-tenant negative tests.
- A guest can join through either an eight-character code or a QR-code token
  without a tenant identifier supplied by the browser.
- Studio policy changes immediately prevent subsequent persistence, while a
  declined or disabled session remains capable of transient live translation.
- Runtime API validation covers service authentication, tenant state errors,
  revision calculation, BCP-47 data, unknown optional fields, and all error
  envelopes.
