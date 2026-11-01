# KasselDIALOG design-system release

The production UI release is based on running source `7878f07e38e3b7d3b685899252e0df981cf7e5a5`, not the full main-branch application. It applies the shared design-system changes from PR #652 while preserving the production documentation wording, legal-information controls, language removals and existing feature availability.

Source commits applied: `fedf07c8`, `bba71960`, `39a7c98b`, `7ff2f362`, `9206007a`, `846ce027` and `f68c4506`. Changes to features absent from the production baseline were omitted. Shared presentation tokens and controls were reconciled; no backend changes are included. The token test was split into smaller checks for the production branch's existing Fallow version.

Validation: 1,262 tests across 131 files; 16 browser cases; build, lint, compiled CSS and Fallow pass. The documentation/consent content, language catalogues and flag mapping have no changes relative to the production baseline.

Build with the existing public production API, WebSocket and Keycloak URLs. Roll out only the frontend using the active runtime Compose configuration with its frontend image replaced. Keep the previous runtime configuration and image for rollback. The source release branch is `release/kassel-design-system-20261101`; PR #652 records the chosen image in the production pin.
