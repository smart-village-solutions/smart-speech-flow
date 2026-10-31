# Change: Integrate Studio legal wording into recording

## Why
Kassel's legal texts are administered by Studio but the conversation application still ignores them. The existing recording flow must display the documentation consent, per-section releases and recording status wording, and bind affirmative actions to the served wording.

## What Changes
- Parse and sanitize optional `legalTexts` independently from recording authorization.
- Use documentation consent plus the guest release in recording questions; require a fresh employee release for every section.
- Preserve guest evidence hashing and archive the employee's release, refusing changed text until the parties review it again.
- Prefer a matching legal localization; explicitly identify source-language fallback when no translation exists.
- Deliver recording status wording through tenant-scoped content routes, preserving truthful liveness states.
- Keep existing installations and statutory-basis notices working without legal text configuration.

## Impact
- Affected specs: studio-content-delivery.
- Affected code: Studio runtime parser/content responses, recording request/evidence, frontend recording dialogs and indicator.
- No quality-session mode, automatic translation, recording enablement or retention-policy change. The user selected integration into the existing recording flow.
