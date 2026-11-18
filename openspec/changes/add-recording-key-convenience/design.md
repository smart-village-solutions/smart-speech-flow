# Recording key convenience design

## Existing behavior

SSF creates and unlocks personal keys in the browser. Private Web Crypto keys
are non-extractable. `createKeyVault` retains them only in tab memory; reloads
lose the unlock. Explicit application logout calls `keyVault.lock()`.
Studio already resolves installation defaults and tenant recording overrides.

## Configuration

Propose `recording.passphraseFileEnabled`, resolved by Studio from the tenant
override, then the installation default, then false. Studio administration shows
the installation value and tenant choices Inherit, Enabled and Disabled.
Changes participate in `configurationRevision`. SSF treats absent policy as
disabled and applies updates to both export and import controls. This setting
does not change recording enablement or authorize archive access.

## Local passphrase files

After successful creation or unlocking, offer an explicit TXT download if the
effective policy permits it. Generate the file from the just-entered passphrase
in the browser; never send it to a server or telemetry. Clear transient input
state when the interaction finishes. Later export requires re-entry because the
application does not retain the passphrase. Warn that TXT is unencrypted and
must be stored privately, especially on shared computers.

The file contains a versioned application label, creation date and the exact
passphrase, without conversation content or personal profile data. Define an
unambiguous round-trip format preserving Unicode and whitespace. Import is
explicit, local, bounded in size, validates the supported format and uses the
ordinary cryptographic unlock checks. A downloaded file is not an independent
backup of private keys or recordings. Revoke temporary object URLs after use.

## Tab-local unlock

Keep unlocked non-extractable CryptoKey objects only in the existing tab's
in-memory vault. Do not persist passphrases or unlocked keys in IndexedDB,
localStorage, sessionStorage, cookies or other browser storage. Do not transfer
unlocked keys between tabs. Existing encrypted personal-key blobs on the server
are unaffected.

Navigation within the application and token refresh for the same authenticated
session preserve the unlock. A page reload, tab closure or a new tab requires a
fresh unlock, even if Keycloak authentication is still valid. This deliberately
preserves the current memory-only storage model.

Bind the in-memory unlock to the authenticated tenant, user and enrolled key
fingerprint/version. Lock on logout, detected authentication expiry, account or
tenant change, enrolled-key replacement and explicit locking. Audit the existing
lifecycle wiring and close any gaps. In-flight unlock operations must not put
keys back into the vault after invalidation. Other tabs hold independent vaults;
a detected end to their authentication locks those vaults as well. Do not promise
immediate detection in a suspended or offline tab.

Non-extractable keys held in memory remain usable by malicious same-origin code;
this design limits their lifetime and avoids extending availability through
persistent local storage. It does not eliminate XSS or shared-computer risks.

## Validation

- Studio inheritance, override/reset, validation and revision behavior.
- Runtime compatibility when the new field is absent; policy updates reflected
  in the SSF controls.
- TXT export/import round trips, malformed and oversized input, Unicode and
  whitespace, explicit download, and no network transmission of passphrases.
- Browser tests for navigation without repeat entry, token refresh and user/key
  changes; reloads and new tabs require a fresh unlock.
- Logout, explicit lock and detected expired sessions, including racing unlocks;
  verify unlocked keys and passphrases are not written to browser storage.
- Existing archive crypto and authorization regressions.
