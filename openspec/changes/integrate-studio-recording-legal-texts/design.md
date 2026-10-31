# Recording legal wording integration

Extend the existing flow rather than introduce a separate consent service. The user authorized the integration and explicitly selected the existing recording flow over adding quality sessions.

The optional Studio block is parsed leniently and sanitized. Recording authorization still requires a valid, enabled recording policy and existing archive, recovery and permission checks. Legal wording alone never enables recording.

A recording question combines the documentation consent (only for a consent legal basis) and the distinct guest release. Repeat the documentation wording for a renewed section as well, so an edited consent cannot silently inherit an earlier agreement. Guest SHA-256 evidence covers the exact sanitized body, including headings. Confirmation/refusal labels come from the applicable choice. Statutory-basis notices remain present rather than being replaced by consent wording.

The employee reviews the staff release before every section, including resumed recordings. The server validates its digest against a fresh policy read, stores the served release with the request, validates it again at the guest's yes, and archives it with the request actor/time. A missing or stale release cannot start recording. Dismissal performs no affirmative action. Existing name, signature and ID checks remain intact.

Resolve legal localizations separately from guest-language availability: exact locale, matching language, then the explicitly identified source locale. Never describe source wording as translated. A configured localization with missing groups falls back to existing copy for those groups; never substitute quality-session consent for documentation consent. Use synthetic wording in tests; private counsel content stays outside git.

Status copy comes from sanitized tenant display content. Substitute waiting/running/stopped/renewed-release text only for matching actual server/liveness states. A disconnected or unacknowledged screen must still say paused rather than running. Show the renewed-release notice after stopping and retain the stop control.

The feature is additive without a database migration. Redis recording-state snapshots gain an optional staff-release record. Old state without it still decodes. A rollback must first check active recording snapshots; never delete active state to force compatibility. Deployment follows the repository's existing release process and requires verification of the exact image and runtime prerequisites.
