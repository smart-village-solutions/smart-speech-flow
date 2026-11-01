# Change: Show Studio legal texts as read-only information

## Why
Kassel needs access to the imported wording before the recording infrastructure cutover. The user approved an informational view that cannot grant consent or release recording.

## What Changes
- Add sanitized, localized legal information to existing tenant-scoped guest/staff content responses, independently of guest language coverage.
- Add an accessible text dialog from guest consent and both conversation screens, clearly marked informational, with actual language/source version and close-only actions.
- Deliver a minimal backport on the exact live Kassel source; do not include recording-mode cutover, data migration, retention changes or archive enablement.
- Forward-port the informational feature to main so it survives later upgrades.
- Per the user clarification on 2026-11-01, always use the two translated UI introduction paragraphs for ordinary entry, omitting Studio explanations there. Preserve the existing Studio response contract and reference dialog. Qualify consent statements for supported statutory recording policies.

## Impact
- Affected spec: studio-content-delivery.
- Code: content parsing/cache/responses and read-only frontend content dialog.
- Operations: gateway/frontend image-only update with protected backups, exact image provenance, compatibility checks and rollback images retained.
