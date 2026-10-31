# Studio legal wording in conversation recording

Studio's optional runtime `legalTexts` block supplies documentation consent, separate guest and employee section releases, and recording status wording. SSF uses these in the existing recording flow. The quality-session text is retained in Studio but is not used for documentation recordings; adding quality sessions is a separate capability.

## Participant flow

1. An employee requests a recording section and explicitly confirms the employee release. This review happens again after every stop, including resumed sections. Dismissing the dialog sends no recording request.
2. The guest sees the full documentation consent and the distinct release for the current section. For a consent legal basis, the documentation choice has its own checkbox and refusal action. The release button stays disabled until that checkbox is checked. Existing first-request name, signature and employee ID checks still apply.
3. Both approvals and existing liveness/acknowledgement checks are required before recording. Either participant can stop it. A new section requires fresh release.
4. Waiting, running, stopped and renewed-release wording follows the actual recording state. Loss of liveness retains the paused warning and stop control, even if the last server phase was on.

Missing legal configuration preserves existing bundled behavior. Statutory-basis notices remain in place rather than being replaced by documentation consent. Legal wording does not grant permissions, configure an archive, enable recording or change retention.

## Languages and evidence

Legal localizations are independent of the guest-language catalogue. SSF first selects an exact locale or matching language, then the declared source locale. Source-language wording has its actual language marked and an explicit original-language notice; it is not represented as a translation. No automatic legal translations are generated.

The gateway sanitizes Studio HTML, and the frontend uses the existing safe rich-text renderer. The exact HTML SHA-256 is retained in archived text evidence. A separate answer digest covers all displayed affirmative/refusal labels, documentation checkbox labels, language and source version as well as the body. The guest sends the gateway's `text_sha256`; old gateways without that field retain HTML-hash compatibility. An edit invalidates a stale answer, including a label-only edit.

The employee release digest is validated on request and again when the guest agrees. Its exact wording, version, actor and request time join the archived consent record. Changing the employee wording while a request is open requires cancelling and requesting a freshly reviewed section. Existing tenant/session ownership and recording permission checks remain mandatory.

## Release boundary

Deploy the gateway and frontend together using the repository's production release process. The optional text block is compatible with existing Studio configurations. Redis recording snapshots gain an optional employee release record; check active recording snapshots before rolling back to code that cannot decode that field, and never delete active state to force rollback compatibility.

At implementation verification, Kassel's live gateway still used revision `2acde0bd2b2da93d4f6c757c57246817be5c2a29` and had no recording archive configured. Studio's actual imported `2026-09-23-draft` block parses successfully, but it does not enable recording. Upgrading that gateway also includes earlier recording-mode changes: follow the recording-mode and archive/retention deployment runbooks rather than treating this as an isolated frontend restart. Private counsel source files, payloads, tokens and runtime credentials must stay outside git.
