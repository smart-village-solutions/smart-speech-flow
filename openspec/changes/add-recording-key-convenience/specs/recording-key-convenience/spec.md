## ADDED Requirements

### Requirement: Configurable passphrase file workflow
Studio SHALL expose an installation default and tenant override for passphrase
TXT export and import. Effective resolution SHALL use the tenant override,
otherwise installation default, otherwise false. SSF SHALL consume the effective
setting, treating an absent setting as disabled. Effective changes SHALL revise
`configurationRevision` and SHALL NOT grant recording or archive permissions.

#### Scenario: Tenant override and reset
- **WHEN** an installation enables passphrase files and a tenant disables them
- **THEN** SSF does not offer export or import for that tenant
- **AND** resetting the override restores the enabled installation default

#### Scenario: Missing configuration
- **WHEN** the effective runtime response omits the setting
- **THEN** SSF does not offer passphrase export or import

### Requirement: Explicit local passphrase backup
When enabled, SSF SHALL offer an explicit TXT download after successful personal
key creation or unlocking and SHALL support explicit import of that file to
unlock keys. Processing SHALL occur locally without sending the passphrase to
servers or telemetry. SSF SHALL explain that the file is unencrypted. It SHALL
preserve the exact passphrase in supported format round trips, bound import
size, reject malformed files and use the existing cryptographic unlock checks.
SSF SHALL NOT persist the passphrase to support later exports.

#### Scenario: Successful unlock and export
- **WHEN** a user successfully unlocks keys and explicitly requests a permitted download
- **THEN** the browser produces the TXT file locally
- **AND** no automatic download or server transmission occurs

#### Scenario: Malformed import
- **WHEN** a file is malformed or exceeds the supported size bound
- **THEN** SSF rejects the import without unlocking keys

### Requirement: Remember unlock within the existing tab
SSF SHALL retain non-extractable unlocked personal keys only in memory within
the existing authenticated tab. Application navigation and token refresh within
the same authenticated session SHALL preserve the unlock. SSF SHALL NOT persist
passphrases or unlocked keys to browser storage or transfer unlocked keys to
other tabs. The unlock SHALL be bound to the authenticated tenant, user and
current enrolled keys.

#### Scenario: Navigation within the application
- **WHEN** an unlocked user navigates between application screens in the same tab
- **THEN** the user need not enter the passphrase again

#### Scenario: Reload or additional tab
- **WHEN** an unlocked user reloads the page or opens another tab
- **THEN** that page requires a fresh unlock
- **AND** an existing Keycloak login alone does not unlock the personal keys

### Requirement: Tab-local unlock invalidation
SSF SHALL invalidate in-memory unlocks on logout, detected authentication expiry,
account or tenant change, enrolled-key replacement and explicit locking.
In-flight operations SHALL NOT restore an invalidated unlock. Other tabs SHALL
maintain independent vaults and lock when authentication termination is detected;
SSF SHALL NOT claim immediate detection in a suspended or offline tab.

#### Scenario: Logout while unlocking
- **WHEN** a user logs out while an unlock operation is pending
- **THEN** its completion does not leave keys unlocked
- **AND** subsequent access requires authentication and a fresh unlock

#### Scenario: Session expiry detected
- **WHEN** a tab detects that its authenticated session has ended
- **THEN** it clears its in-memory unlock

#### Scenario: Close and reopen
- **WHEN** a user closes the unlocked tab and opens SSF again
- **THEN** no unlocked keys are restored from browser storage
- **AND** a fresh unlock is required
