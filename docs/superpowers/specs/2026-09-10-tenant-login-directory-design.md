# Tenant Login Directory and Multi-Realm Staff Authentication

## Context

Smart Speech Flow (SSF) has one public frontend at
`https://dialog.kassel.de`, while each organisational tenant has a separate
Keycloak realm. A single fixed realm at `/login` can therefore no longer select
the correct identity boundary. SVA Studio is the control plane and provides the
authoritative set of SSF-enabled tenants.

The public start page must expose only a neutral **Login** text link. The direct
SVA Studio login is an operator entrypoint for informed users and must not be
advertised on the SSF start page. `/admin` is reserved for a different future
purpose and is not the tenant-login entrypoint.

## Goals

- Route the start-page **Login** link to `/login`.
- Present an accessible, alphabetically sorted directory of available tenants.
- Select the correct Keycloak realm from Studio-controlled data.
- Continue directly to the tenant's conversation administration when a usable
  realm session already exists; otherwise show that realm's Keycloak login.
- Bind every authenticated request to the canonical Studio tenant ID and reject
  cross-tenant or browser-selected tenant context.
- Keep Studio service credentials and internal APIs out of the browser.

## Non-Goals

- Define the future behavior of `/admin`.
- Advertise or reproduce the SVA Studio root login.
- Allow users to type or otherwise supply arbitrary realm names.
- Support multiple Keycloak installations for one SSF installation.
- Add tenant branding, logos, descriptions, or availability states to the
  directory in the first delivery.

## Studio Contract

SSF calls the following tenant-unbound internal endpoint with its existing
client-credentials identity:

```http
GET /internal/plugins/ssf/v1/admin-login-tenants
Authorization: Bearer <SSF service token>
X-Correlation-Id: <correlation id>
```

The successful response is:

```json
{
  "contractVersion": "1.0",
  "directoryRevision": "sha256:<64 lowercase hexadecimal characters>",
  "tenants": [
    {
      "id": "tenant-kassel",
      "displayName": "Stadt Kassel",
      "realm": "kassel-ssf-2025"
    }
  ]
}
```

`id` is the immutable canonical Studio tenant ID. `displayName` is safe for
public display. `realm` is the provisioned Keycloak realm identifier and is
technical routing data rather than the tenant identity. Known fields are
strictly validated, while unknown optional V1 fields may be ignored for forward
compatibility.

Studio returns only non-root tenants for which the SSF plugin, tenant realm,
OIDC client, roles, claims, and tenant baseline are active and ready. Suspended,
partially provisioned, internal, root, and test tenants are omitted. Tenant IDs
and realm names are unique within the response. An empty list is a valid
successful response.

The service identity needs a dedicated least-privilege permission such as
`ssf.admin-login-directory.read`. Invalid service authentication returns 401,
missing permission returns 403, and temporary directory failure returns 503.
Errors use the established Studio V1 error envelope and preserve the correlation
ID without exposing tenant details.

## Keycloak Provisioning Contract

For every listed tenant, Studio provisions the same configured public SSF OIDC
client in that tenant's realm. It uses Authorization Code Flow with PKCE S256,
disables implicit flow and direct access grants, and permits the exact SSF web
origin plus the required `/login/*` redirect paths.

Tokens contain the expected audience and staff role as well as the signed
canonical `studio_tenant_id` and `ssf_authorization_revision` claims. A tenant
must not enter the directory until this complete baseline is ready. The
installation supplies one trusted Keycloak base URL and one public client ID;
those values are not repeated per tenant in the directory.

## SSF Data Flow

The start page links **Login** to `/login`. This route calls the public,
read-only SSF gateway endpoint `GET /api/login/tenants`. The gateway obtains a
service token, calls the internal Studio directory, strictly validates the
response, and returns only the validated directory fields. The service token
never reaches the browser.

The frontend sorts tenants by `displayName` using German locale-aware ordering,
with the immutable tenant ID as a deterministic tie-breaker. Selecting a tenant
navigates to `/login/:tenantId`. The frontend resolves that ID only against the
validated directory and initializes `keycloak-js` with the installation's
trusted Keycloak base URL, the selected entry's realm, and the configured public
client ID. The callback returns to the same tenant-qualified route.

Keycloak's `login-required` initialization decides the visible result. An
existing usable session for the selected realm immediately opens the existing
conversation dashboard; otherwise the browser is redirected to that realm's
Keycloak login and opens the dashboard after a successful callback. Logout is
performed in the selected realm and returns to `/login`.

The URL uses the Studio tenant ID rather than the realm. This keeps the public
application route stable if Studio later migrates a tenant to a different realm.
The route parameter selects an entry but is never trusted as authorization.

## Gateway Authentication

The current single configured issuer becomes an allowlisted multi-realm issuer
strategy. The gateway may inspect an unverified token issuer only to choose a
candidate verifier; it performs no network request until the issuer exactly
matches the trusted Keycloak base URL plus a realm from a currently validated
Studio directory. It then validates signature, issuer, audience, expiry, and
the required staff role through discovery and JWKS.

After cryptographic validation, the signed `studio_tenant_id` must equal the
Studio tenant mapped to the validated issuer realm. The existing immutable
Studio tenant context and authorization-revision checks remain authoritative.
No header, query parameter, request body, cookie, path parameter, or unverified
claim can override that context.

JWKS and the validated tenant directory use bounded caches. A previously
validated directory may be used only within its configured freshness window.
Once that window expires, inability to refresh the directory fails closed for
new login selection and issuer admission.

## User Interface and Errors

The `/login` page uses the existing application header and footer and states,
in German, that the user should select their department or organisation. Each
tenant is presented as one keyboard-accessible link or button bearing its
public display name.

While loading, the page presents a non-disruptive loading state. An empty
directory states that no organisations are currently available. A Studio or
gateway failure presents a neutral unavailable message and a retry action.
Malformed responses, duplicate IDs, duplicate realms, unsupported contract
versions, invalid revisions, and unsafe realm identifiers are rejected as a
whole; SSF never falls back to a configured default or user-supplied realm.

The start page no longer exposes a direct SVA Studio link. Existing temporary
legacy behavior at `/admin`, if enabled during migration, receives no start-page
entry and remains outside this feature until replaced separately.

## Testing

- Contract tests cover valid, empty, malformed, duplicate, unauthorized,
  forbidden, and unavailable Studio responses.
- Gateway tests prove that service credentials stay server-side and only
  validated directory data reaches the public endpoint.
- Authentication tests cover two allowed realms, unknown issuers, realm/tenant
  claim mismatches, invalid signatures, wrong audiences, missing roles, expired
  directory data, and preserved customer-route behavior.
- Frontend tests cover the `/login` link, German alphabetical ordering, empty
  and retry states, tenant selection, existing SSO sessions, Keycloak redirects,
  callbacks, logout, and rejection of unknown tenant routes.
- Production-like verification covers at least two provisioned tenant realms
  and confirms that neither can read or mutate the other's conversations.

## Rollout

Studio deploys and verifies the tenant directory and per-realm OIDC baseline
before SSF enables directory-based login. SSF then deploys gateway support for
the directory and multi-issuer validation before the frontend exposes the new
selection page. Rollback restores the previous SSF frontend and gateway images;
the additive Studio endpoint and tenant realm configuration remain in place.
