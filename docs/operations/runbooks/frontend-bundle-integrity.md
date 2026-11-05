# Frontend bundle integrity

The frontend's JavaScript handles archive passphrases and encrypts recordings in
the browser. Whoever controls the server that serves it could ship a modified
bundle. This runbook covers the policy the image sends, the fingerprint every
deploy records, and the monitor that compares the live site with it (#620).

## What the image sends

Every response carries a strict Content-Security-Policy, `X-Frame-Options:
DENY`, `nosniff` and `X-XSS-Protection`. The policy is written at image build
time from the build values (`services/frontend/security/securityPolicy.ts`), so the
API, socket and Keycloak origins are always the ones compiled into the bundle.
The build argument `SSF_CSP_MODE` selects `report-only` (the default) or
`enforce`. A build that leaves it out never enforces by accident.

In Report-Only mode the policy has no `report-uri`: violations show only in the
browser console. On an iPad, connect it to a Mac and use Safari's Web Inspector.

### Before enforcing on production

1. Testers walk every screen on real iPads with the Web Inspector open, and see
   no policy messages.
2. Check that every Studio media URL (language icons, logo, favicon) is on
   `dialog.kassel.de`: open the language picker and the header in Safari and
   look at the image URLs in the Web Inspector. A URL on any other host would
   be blocked once enforced; raise it before enforcing.
3. Build with `--build-arg SSF_CSP_MODE=enforce` from then on, and record the
   deploy like any other.

## Recording a deploy

Every frontend deploy records what the new image serves, whoever deploys and
whatever the image. An unrecorded image raises the alarm.

1. Build the image on the host as usual (Report-Only unless
   `--build-arg SSF_CSP_MODE=enforce` is given).
2. Check what production serves now. The file's `current` must be live; if
   production still matches `previous` (a rollback, or an apply that never
   happened), first record the live image the same way, merge that, and only
   then record the new one. Otherwise the live version drops out of the file
   and the monitor alarms. On the very first recorded deploy there is no file
   on main yet: skip this check, and give `record` a path that does not exist.

   ```bash
   git fetch origin
   git show origin/main:deploy/production/frontend-manifest.json > /tmp/main-manifest.json
   python3 -m scripts.frontend_integrity check --url https://dialog.kassel.de \
     --manifest /tmp/main-manifest.json --out /tmp/verdict.json
   ```

3. Record the new image, starting from main's copy of the file (the host's
   checkout can lag behind). This runs on the host, in the repository checkout,
   with Python 3.10 or newer, and `sudo` if Docker needs it:

   ```bash
   python3 -m scripts.frontend_integrity record \
     --image ssf-backend-frontend:prod-<sha> --commit <full sha> \
     --manifest /tmp/main-manifest.json --out /tmp/frontend-manifest.json
   ```

4. Copy `/tmp/frontend-manifest.json` into the rollout branch as
   `deploy/production/frontend-manifest.json`, next to the image pin.
5. **Merge the record PR before `scripts/deploy-production.sh --apply`.** The
   file keeps the version before it as `previous`, and the monitor accepts both,
   so production keeps matching while the old image still runs.
6. After the apply, run the `check` command from step 2 against the merged
   file. It prints `match current`.

A rollback to the previous image stays quiet. Rolling back further needs that
image recorded again.

## The monitor

`.github/workflows/frontend-integrity-monitor.yml` runs at minutes 7, 22, 37 and
52 of every hour, and does nothing until the repository variable
`FRONTEND_MONITOR_URL` is set. Each run fetches the site like an iPad (Safari
user agent, gzip), and compares it with `current`, then `previous`:

- `/` and the deep link `/join/monitor-probe` must serve the recorded `index.html`;
- the policy header must have the recorded name and value;
- every other recorded file must have its recorded hash.

### Switching it on

1. Record a deploy (above), so the file exists on main.
2. Tell Philipp that frontend deploys now record a fingerprint, and that an
   unrecorded deploy raises the alarm.
3. Create the labels: `gh label create bundle-integrity` and
   `gh label create bundle-integrity-test`.
4. Set the variables `FRONTEND_MONITOR_URL=https://dialog.kassel.de` and,
   optionally, `FRONTEND_MONITOR_ASSIGNEES` (space-separated GitHub logins with
   write access).
5. Run the workflow by hand once (Actions, "Run workflow") and read its log.

### Responding to an alert

The workflow keeps one open issue labelled `bundle-integrity`, comments only
when the differences change, and says once when the site matches again. It
never closes the issue.

1. Read the findings, then compare by hand with the `check` command above.
2. If a deploy explains it (an unrecorded image, a record PR not yet merged),
   record and merge, and close the issue with the explanation.
3. Otherwise treat the host as possibly compromised: stop recording, redeploy a
   known image from a clean checkout, and assume archive passphrases typed
   since the last matching run may be known. Rotate the affected users' archive
   keys, review archive access, and escalate as a security incident.

Anything but a match is looked at again two minutes later, and only a result
that persists is reported, so a deploy's brief 502 does not open an issue. A
site that does not answer twice is reported like a mismatch, with fixed text:
blocking GitHub's address ranges must not silence the monitor.

### Self-test (the #620 acceptance demonstration)

Run the workflow by hand with "self_test" ticked. It builds the current commit
with placeholder hostnames, records it, shows that the untouched container
matches, appends one byte to a chunk inside the container, shows the monitor
alarming, and opens an issue labelled `bundle-integrity-test`. Production is
never contacted. Close that issue afterwards.

## Limits

- The monitor proves that production still serves what was deployed. It does
  not prove that the deployed build matches the public source: a build host
  compromised by deploy time goes unnoticed.
- It sees only what GitHub's network is served. A bundle served only to chosen
  visitors goes unseen, and so does content served only Brotli-compressed (the
  monitor asks for gzip; Safari also accepts Brotli).
- It checks `/`, one deep link and the recorded files. Different content on
  other paths, such as the guest `/s/...` entry paths, goes unseen.
- A swap shorter than the 15-minute interval can be missed, and hashed assets
  are cached for a year, so a tampered file served even briefly stays in
  visitors' caches.
- It accepts a return to the previous recorded version.
- GitHub disables scheduled workflows after 60 days without repository
  activity. If the Actions page shows the workflow disabled, re-enable it
  there; a monthly glance at its last run catches this.
- The policy blocks a second Keycloak host, or Studio media on any host other
  than dialog.kassel.de, until the policy changes. Language icons then show no
  image (`FlagAvatar` has no load-error fallback).
- `form-action 'self'` holds because keycloak-js logs out with GET. Its POST
  logout would need the Keycloak origin in `form-action`.
- `style-src` allows inline styles: Radix dialogs inject computed `<style>`
  tags. No inline script is allowed.
