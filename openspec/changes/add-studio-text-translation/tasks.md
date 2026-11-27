## 1. SSF and Studio contract

- [x] 1.1 Reconcile PR #712 with current main and reuse its strict engine and conversation admission controls.
- [x] 1.2 Verify both SSF v1 routes, instance credentials, language discovery, batch order and marker integrity.
- [x] 1.3 Add a server-side Studio provider adapter with trusted origin selection for Magdeburg staging. Reuse Studio's job lifecycle and placeholder logic. Verify provider selection, language mapping, batching and error handling through the existing Studio entry points.
- [ ] 1.4 Agree on request limits and retry behavior using representative batches. Verify client parsing, long inputs, invalid credentials, and temporary overload.

## 2. Havelland pilot

- [ ] 2.1 Measure representative German-to-English, German-to-Polish and German-to-Japanese translations. Establish baseline and acceptance thresholds, then verify live conversation latency under concurrent background load.
- [ ] 2.2 Deploy and verify Havelland with a dedicated pilot credential and a documented rollback. Verify response and logging behavior with synthetic data.
- [ ] 2.3 Configure Magdeburg staging, check the connection, and verify the resulting translations for representative News and Static Content jobs.
