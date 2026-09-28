# Design

The gateway first admits a token issuer only when exactly one entry in the
Studio login directory maps to it. It then validates the token's RS256
signature, issuer, audience, expiry, and non-empty subject. Only after that
validation does it overwrite an internal tenant marker with the directory's
tenant ID. Downstream tenant context and optional authenticated customer
session checks consume this marker, never a caller-supplied legacy claim.

Runtime Configuration V1 remains fetched using that tenant and must return
the same tenant ID. Its authorization revision remains configuration metadata
but is no longer an access check against user-token data. Feedback reads and
the telemetry probe retain an explicit role dependency separate from ordinary
conversation authentication.

The producer-first removal is unsafe: the gateway must be deployed first,
then real attribute-free tokens from two realms must pass create/read/terminate
and cross-tenant denial checks before Studio removes its legacy token mapping.
