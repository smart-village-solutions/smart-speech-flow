# Kassel read-only legal information backport

This release branch starts at the exact live source `2acde0bd2b2da93d4f6c757c57246817be5c2a29`. It adds a read-only information view without importing the later recording-mode cutover. Do not build these Dockerfiles from main: main's gateway modules require a different runtime composition.

The API image inherits the verified running gateway image and replaces only five content modules. The frontend compiles this branch with the existing public Vite settings and inherits the verified running Nginx image. Existing runtime dependencies and infrastructure stay in place. Before building, verify the local base tags against the recorded running image IDs; record the immutable resulting IDs, exact source revision and labels. Build contexts contain no runtime credentials or private counsel payloads.

Use a protected copy of the production Compose configuration from this base revision, validated against the actual live environment, mounts, labels, resources, networks and security settings. Replace only gateway/frontend image references and preserve actual environment values. Run `up -d --no-deps` for those two services only. Do not restart Redis, change volumes, run migrations, enable recording or alter retention. Wait for a quiet conversation window before replacing the gateway.

Before cutover, retain protected runtime/Compose snapshots and both old image IDs. Verify candidate modules, labels, unchanged runtime dependencies, frontend public API/WS/OIDC settings, and actual Studio payload parsing. After cutover, verify both healthchecks, public entry/login behavior, legal text source/version, existing policy and unchanged non-target containers. Roll back by starting both previous image IDs with the saved configuration if verification fails. No database downgrade or volume restore is required because this change introduces no persistent data format or write behavior.

The information dialog has only a Close action. It is not a consent collection or recording-release path. Quality-session wording may be read as information; reading it does not create or authorize a quality session.
