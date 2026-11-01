# KasselDIALOG design-system release

The final production UI release is `45f4e6b2`, combining the PR #652 design changes with deployed source `49e982b3ff159a06c4537ba53254d91d5b4b91c6`. The latter updates the general introduction for ordinary conversations. Its consent/content files, translations, language selection and flag mapping are unchanged in the release. The image is built from an immutable archive of the release source, not the full main-branch application.

Source commits applied: `fedf07c8`, `bba71960`, `39a7c98b`, `7ff2f362`, `9206007a`, `846ce027` and `f68c4506`. Changes to features absent from the production baseline were omitted. Shared presentation tokens and controls were reconciled; no backend changes are included. The token test was split into smaller checks for the production branch's existing Fallow version.

Validation: 1,247 tests across 130 files; 16 browser cases; build, lint, compiled CSS and Fallow pass. Independent review confirms that the production hotfix is an ancestor and no absent features were reintroduced. The earlier candidate `a1280891` was superseded before activation when production advanced to `49e982b3`.

Build with the existing public production API, WebSocket and Keycloak URLs. Roll out only the frontend using the active runtime Compose configuration with its frontend image replaced. Keep the previous runtime configuration and image for rollback. The source release branch is `release/kassel-design-system-20261101`; PR #652 records the chosen image in the production pin.
