## 1. Gateway

- [x] 1.1 Classify every rejection in `require_ssf_user` with a closed reason
  code, one log line with the correlation ID, and a labelled counter.
- [x] 1.2 Return an authenticated principal whose tenant is the
  directory-matched tenant; reject a disagreeing `studio_tenant_id`.
- [x] 1.3 Convert every downstream consumer to the principal, including the
  customer HTTP, polling and websocket paths.
- [x] 1.4 Guard that no gateway module reads the tenant claim.

## 2. Realm contract and operations

- [x] 2.1 Refresh `ssf-realm.json` as the SSF realm contract and guard it.
- [x] 2.2 Make the tenant-isolation smoke test name missing revision, role and
  stale revision precisely.
- [x] 2.3 Add the read-only tenant authentication audit.
- [x] 2.4 Document onboarding verification, diagnosis and realm provisioning.

## 3. Verification

- [x] 3.1 Run every repository gate and the rebuilt-image integration tests.
- [ ] 3.2 Deploy after sva-studio#1325/#1480 and verify #1319 in production,
  then pass the protected two-realm acceptance in sva-studio#1350 with a fresh
  token.
