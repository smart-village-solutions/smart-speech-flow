# Change: Recording passphrase backup and session unlock

## Why

Users may forget their recording passphrase. They need an optional local TXT
backup and should unlock their personal keys only once per authenticated browser
session within the existing tab, without surviving page reloads or tab closure.

## What Changes

- Add a Studio installation default and tenant override for offering a local
  passphrase TXT download and file import. The proposed default is disabled;
  tenants can inherit, enable or disable the option.
- Generate downloads and read imported files entirely in the browser. Offer
  export after successful key creation or unlocking while the entered passphrase
  is still available; do not retain it for later export.
- Retain non-extractable unlocked personal keys only in memory in the existing
  tab. Navigation within the application preserves the unlock; reloads, closing
  the tab and new tabs require a fresh unlock. Never persist the passphrase or
  unlocked keys in browser storage.
- Invalidate the remembered unlock on logout, session expiry, account or tenant
  change, key replacement, and explicit locking in the affected tab. Detected
  authentication termination also locks other tabs independently.

## Impact

- Studio owns configuration inheritance and effective policy delivery; SSF
  consumes the effective value through the runtime configuration contract.
- Preserves the current memory-only personal-key lifetime. Review and close
  lifecycle gaps around logout, detected expiry and identity changes without
  adding persistent browser key storage or cross-tab key sharing.
- Disabling TXT support controls the application's offered workflow; it cannot
  prevent a user from manually copying their own passphrase.
- No changes to archive encryption, recovery recipients or server-side custody
  of personal private keys.
- The user approved implementation in SSF and Studio on 2026-11-18, with
  unlock restricted to the existing tab.
