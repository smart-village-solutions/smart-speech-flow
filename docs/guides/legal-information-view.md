# Read-only legal information

When Studio provides valid legal wording, guests can open **Consent and recording conditions** from the consent page and the conversation's legal-links area. Staff can open the same information from their conversation screen.

The dialog displays the available documentation, quality-session and participant-release wording, with the actual source locale and version. A missing translation uses the declared source wording; it is not presented as a translation. HTML is sanitized by the gateway and rendered with the existing allowlisted rich-text component. The source may still be a draft and contain its original contact placeholder.

This is an informational, close-only view. Opening, reading, scrolling, closing or pressing Escape sends no consent, session-activation or recording-release request. It does not enable storage, change retention, start an archive or create a quality session. Existing consent and recording controls elsewhere retain their own behavior.

Legal information is served through the existing tenant/session-scoped content routes, independently of whether Studio provides that guest language's other copy. Missing or malformed optional legal information hides the additional action while retaining the existing page and legal links.

## Kassel compatibility release

The initial Kassel release is a narrow backport on source `2acde0bd2b2da93d4f6c757c57246817be5c2a29`, separately published for source review. It retains the existing storage/activation contract and does not import the later recording-mode infrastructure cutover. The same informational feature is forward-ported to main so later upgrades retain it.

The backport gateway inherits the verified running image and replaces only five content modules. The frontend compiles the same source branch with the existing public API, WebSocket and OIDC settings, then inherits the verified running Nginx image. Source revisions, immutable image IDs and pre/post configuration checks must be recorded. Deployment replaces only the two application services; existing volumes, Redis, policies, sessions and infrastructure remain in place. Retain both previous image IDs and protected Compose/runtime snapshots for a direct image rollback.
