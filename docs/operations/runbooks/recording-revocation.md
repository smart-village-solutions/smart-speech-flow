# Recording Revocation Runbook

## Scope

The gateway's nightly revocation check (#619). It removes access to archived
conversations from people who lost the Studio permission behind it:

- a reviewer who no longer holds `ssf.recording.review` loses every open
  assignment and its key wraps;
- a supervisor who no longer holds `ssf.recording.supervise` loses the wraps
  they recovered through exceptional access (#617a).

An employee's access to their own conversations is never touched. Leavers stay
an administrator's decision (the leavers panel, #617d).

Migration 011 must be applied, and the gateway must have an archive. The check
runs only for tenants in the archive writers file.

## Every command names its stack

On the gateway host:

```bash
source scripts/lib/production-common.sh
```

## When it runs

- Every 15 minutes the gateway looks whether the night's run is due. From
  02:00 Europe/Berlin it runs once per tenant and day.
- A run is claimed in `revocation_runs` (tenant, date). With several gateways,
  only one runs it. A run that started and never finished, as after a crash, is
  claimed again after 6 hours.
- Each run is audited: what it withdrew and deleted
  (`recording.verification.withdrawn.permission_revoked`, `key_wrap.revoked`),
  or why it skipped (`recording.revocation.skipped.<guard>`).

## Guards

The check deletes access on its own, so it trusts the Studio directory only when
all of these hold. Otherwise it skips the tenant and deletes nothing.

| Guard | Skips when | Usual cause |
|---|---|---|
| `unreadable` | the directory cannot be read | Studio down, the runtime token failing |
| `implausible` | the directory lists none of the tenant's users with an active key | an empty or truncated answer |
| `unstable` | a second read 60 s later carries another `directoryRevision` | permissions being edited during the run |
| `bound` | the run would remove access from more than 2 people **and** more than 25 % of everyone holding reviewer or recovered access | a role-mapping fault, or a real mass removal |

A skipped tenant is checked again the next night.

## Alerts

`RecordingRevocationStale` (warning): the oldest successful run across tenants
is more than 26 hours old.

1. Find the skip in the audit log or the gateway log:

   ```bash
   production_compose logs api_gateway | grep recording_revocation
   ```

2. For `unreadable` or `unstable`, check that the gateway reaches Studio
   (`StudioPolicyReadsFailing` fires too when it cannot). The next night's run
   usually succeeds.
3. For `implausible`, compare the Studio directory with the tenant's key
   holders before anything else. Do not override it.
4. For `bound`, confirm with the tenant's administrator that the removal is
   real (for example, a whole reviewer team left). Then run the check by hand
   with `--allow-mass`, as below.

## Running it by hand

```bash
production_compose exec api_gateway \
  python -m services.api_gateway.recording.revocation_cli --tenant <tenant-id>
```

- It reads the same environment as the gateway, applies the same guards, and
  records its actor as `operator`.
- Exit code 0: it revoked what it found. 1: a guard skipped it, named on
  standard output. 2: recording or Studio is not configured in that container.
- `--allow-mass` lifts only the `bound` guard. Use it only after the
  administrator has confirmed the removal.
- A manual run does not count as the night's run: the metric moves only with the
  scheduled one.

## Deploying a change to the alert rule

Prometheus mounts `alert_rules.yml` as a single file, so it keeps the old rules
after the checkout updates. Restart it and compare hashes:

```bash
production_compose restart prometheus
sha256sum monitoring/alert_rules.yml
production_compose exec prometheus sha256sum /etc/prometheus/alert_rules.yml
```

## Known limits

- Access a reviewer or supervisor saved while authorised (a wrap blob and the
  ciphertext) still opens what it covered. Revocation stops future access only
  (spec §19).
- A revoked reviewer's open assignment returns to the employee as *Withdrawn*.
  The employee assigns someone else.
