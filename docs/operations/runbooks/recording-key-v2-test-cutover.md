# Recording protocol v2: disposable test-data cutover

This runbook applies only to the legacy recording/recovery test data explicitly
identified as disposable in the approved `update-recording-key-lifecycle` change.
It is not a migration or a production-data deletion authorization. Do not run it
against an unreviewed database or any tenant with records that must survive.

The v2 runtime marks existing tenants as protocol generation 1 and rejects
incompatible recording operations with `RECORDING_PROTOCOL_UPGRADE_REQUIRED`.
Ordinary conversations remain usable. There is no automatic reset on startup.
After cutover, normal personal-key replacement preserves old blobs, grants and
reviews, and organisation-key replacement preserves historical key references.

## Preconditions and scope

Obtain explicit operator authorization for the exact tenant, database and archive
storage/spool targets. Record the backup and rollback decision before proceeding.
Deploy compatible Gateway, SSF, Studio and the Keycloak exchange-assurance mapper
through their established deployment processes. Studio's server client and user
session must belong to the target tenant realm, with allowed exchange audience,
permissions and original MFA context. Test the actual exchange before enabling
organisation administration; client credentials are not a fallback.

The reset CLI uses `SSF_RECORDING_OWNER_DATABASE_URL` and its separate
`SSF_RECORDING_OWNER_DATABASE_PASSWORD`. Supply them through the approved secret
mechanism; never include passwords in shell arguments, saved output or tickets.
It requires the offline database operator role. Database name is checked against
the live connection. Audit history and gateway signing public keys are preserved.
Feedback, usage, ordinary conversation metadata and other tenants are untouched.

## Review the inventory

Set shell variables to the exact reviewed non-secret names. `storage_target`
identifies the existing archive endpoint, tenant bucket and spool locations;
do not include access credentials. Save the inventory to a restricted file.

```bash
umask 077
python -m services.api_gateway.recording.reset_legacy_test_data \
  --database "$recording_database" \
  --tenant "$recording_tenant" \
  --storage-target "$storage_target" > "$inventory_file"
```

The default is read-only. The JSON contains the database, tenant, protocol
generation, per-table counts and content fingerprints, archive bucket, known
object versions and a digest. It contains no personal private-key blobs or
conversation contents. Treat its identifiers as operational metadata and keep
the file restricted. Unknown tenant tables, foreign-key dependencies and schema
cycles fail closed rather than expanding the deletion scope.

Stop recording writers, uploaders and retention workers before the final
inventory review. Use the existing archive retention/admin process to clear
**only** the approved disposable tenant's object versions and pending spool
items, respecting enforced retention and holds. The CLI neither deletes object
storage nor bypasses its retention. Check both archive sites and spool state;
its database inventory cannot discover uploaded objects absent from database
metadata. If the storage cannot be cleared, stop here. Keep the saved inventory
until storage cleanup is verified; deleting metadata first would orphan objects.

If archive cleanup updates stored-object metadata, produce a new dry run and
review its digest after cleanup. The apply step requires the exact unchanged
inventory; table locks prevent concurrent writes during its recheck.

## Apply the reviewed test reset

Construct the confirmation from the reviewed database, tenant and full `digest`.
The two explicit flags attest that the operator has stopped writers and checked
archive/spool cleanup. They are not checks performed by the CLI.

```bash
python -m services.api_gateway.recording.reset_legacy_test_data \
  --database "$recording_database" \
  --tenant "$recording_tenant" \
  --storage-target "$storage_target" \
  --apply --writers-stopped --storage-cleared \
  --confirm "$recording_database:$recording_tenant:$reviewed_digest"
```

Only generation 1 is eligible. Wrong database, changed inventory, incomplete
confirmation or a newer generation refuses the operation. The transaction
removes the selected tenant's legacy recording/key/recovery data in dependency
order, temporarily permits removal of its closed verification notes, restores
that trigger and sets generation 2. The known legacy ceremony/recovery-key cycle
is broken only within the same selected-tenant transaction. Any failure rolls
back changes and trigger state. The retained audit chain records the reset digest.

Do not automate this command into application startup or deployment. Do not
reuse the confirmation for another target. There is no automatic rollback to
legacy rows after new v2 records have been created.

## Acceptance after cutover

Resume services through the existing operational process. In Studio, generate
an organisation key locally, save the complete file and explicitly activate it.
Enroll personal access with the existing passphrase workflow, then verify:

- Ordinary conversations work without recording setup; recording requires both keys.
- Personal replacement retains old recordings and assignments under the old passphrase.
- Organisation replacement applies to new recording windows; old key files remain useful.
- A separately transfer-authorized person can load the organisation file locally and
  grant only the confirmed recordings to the current target key version.
- A reviewer can sign with the assignment's usable version; completion removes only
  review-dependent access. Explicit revocation still blocks access.
- Studio/Gateway requests contain no private organisation key, plaintext content
  key or personal passphrase. The final SSF menu has no threshold recovery entry.

Run the local integration fixtures against isolated test databases only. Never
point integration suites at a deployed database: existing fixtures may truncate
or delete their test tables.
