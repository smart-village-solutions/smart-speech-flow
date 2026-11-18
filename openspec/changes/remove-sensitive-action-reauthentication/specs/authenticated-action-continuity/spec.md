## ADDED Requirements

### Requirement: One login authorizes actions throughout the valid session
SSF and Gateway SHALL accept a valid authenticated tenant user session for all
otherwise authorized actions, including sensitive recording and administrative
actions. They SHALL NOT require account reauthentication, action-specific MFA,
`acr=mfa` or a maximum `auth_time` age for those actions. Optional and required
MFA SHALL remain login policies; password-only login accepted by an optional-MFA
tenant SHALL suffice for subsequent authorized actions. This rule SHALL cover
currently exposed legacy workflows and planned organisation-key and transfer APIs.

#### Scenario: Password-only login under optional MFA
- **WHEN** a user admitted without MFA performs an otherwise authorized sensitive action
- **THEN** the action proceeds without password or second-factor challenge
- **AND** no `STEP_UP_REQUIRED` response or enrollment requirement is introduced

#### Scenario: Older MFA login
- **WHEN** the original MFA login is older than 300 seconds but the user session and presented token are valid
- **THEN** a sensitive action proceeds without a freshness challenge
- **AND** missing optional `acr` or `auth_time` claims alone do not deny the action

#### Scenario: Required MFA at login
- **WHEN** a tenant requires MFA
- **THEN** login requires the configured second factor
- **AND** later authorized actions in that valid session require no repeat challenge

### Requirement: Authentication and authorization remain enforced
Gateway SHALL continue validating user bearer signature, issuer, audience,
expiry, subject and tenant context and checking the action's required effective
permissions. Session refresh SHALL continue through the existing supported flow.
A session that cannot be refreshed or is otherwise invalid SHALL require normal
login. Token exchange SHALL preserve verified user identity and authentication
context without fabricating claims, but original MFA age SHALL NOT gate actions.
Service credentials or unverified actor headers SHALL NOT replace user authority.

#### Scenario: Expired token with successful refresh
- **WHEN** a token expires and the existing session can refresh it
- **THEN** the client uses the refreshed token without an action-specific login challenge

#### Scenario: Invalid or ended session
- **WHEN** no valid user authentication can be obtained through the existing refresh flow
- **THEN** the action is denied and normal login is required

#### Scenario: Missing authority
- **WHEN** a valid session lacks an action's permission or has the wrong tenant
- **THEN** the action is denied without granting additional authority or offering MFA as a permission substitute

#### Scenario: Delegated older login
- **WHEN** Studio exchanges a valid user token from a login older than five minutes
- **THEN** an otherwise valid and authorized delegated action proceeds without step-up

### Requirement: Local key unlock and action safeguards stay independent
Unlocking the user's own encrypted keys SHALL, within a valid authenticated
session, depend only on the matching local passphrase, labelled **Zugangsschlüssel**.
Unlock SHALL NOT require another account login, login password, second factor or
email confirmation. This SHALL apply to active and usable historical versions,
including after explicit lock or reload. Fetching the user's encrypted key blob
SHALL use existing session authentication without any action-specific challenge.
Removing account reauthentication SHALL preserve local personal-key unlocking,
verified-email requirements, existing email confirmations, explicit action
confirmation, cryptographic possession proofs, audit, replay protection and
preparation/challenge expiration. Personal passphrases and organisation private
keys SHALL remain local according to their existing custody rules. An unlocked
personal key SHALL retain its existing tab-local lifetime and invalidation rules.

#### Scenario: Locked personal key
- **WHEN** a valid authenticated user opens content requiring a locked personal key
- **THEN** the application requests its local passphrase without redirecting to account login
- **AND** the passphrase is not sent to a server

#### Scenario: Unlock again after explicit lock or reload
- **WHEN** a user's session is valid and their own keys are locked after explicit lock or page reload
- **THEN** the matching local Zugangsschlüssel suffices to unlock the requested usable key version
- **AND** no account-login redirect, login-password entry, MFA or email confirmation is required

#### Scenario: Incorrect personal passphrase
- **WHEN** a valid authenticated user enters an incorrect Zugangsschlüssel
- **THEN** the key remains locked and a local unlock error is shown
- **AND** the application does not initiate account reauthentication

#### Scenario: Long-running cryptographic operation
- **WHEN** a computation crosses the former MFA freshness deadline
- **THEN** it is not stopped merely because of original login age
- **AND** current authentication, authorization, key validity and preparation expiry are still checked

#### Scenario: Expired possession preparation
- **WHEN** an organisation-key activation or transfer preparation expires
- **THEN** commit is rejected and a new preparation is required
- **AND** obtaining that preparation does not require a fresh account login while the session is valid
