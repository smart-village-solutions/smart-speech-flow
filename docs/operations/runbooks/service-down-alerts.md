# Runbook: service-down and capacity alerts

## What each alert means

| Alert | Fires when | Meaning |
| --- | --- | --- |
| `ASRScrapeDown` / `TranslationScrapeDown` / `TTSScrapeDown` | Prometheus cannot scrape the service for 2 minutes | The container is gone, wedged, or unroutable. The stage fails for every message. |
| `ASRServiceDown` / `TranslationServiceDown` / `TTSServiceDown` | The service answers but reports `<svc>_health_status == 0` for 2 minutes | The process is alive and self-reporting unhealthy — usually the model failed to load or the GPU is unavailable. |
| `APIGatewayScrapeDown` | Gateway unscrapeable for 1 minute | Total outage. |
| `GPUMemoryPressure` | `DCGM_FI_DEV_FB_USED / DCGM_FI_DEV_FB_TOTAL > 0.95` for 5 minutes | See the threshold note below. |
| `TranslationLatencyHigh` | p95 `translation_request_latency_seconds` > 3s for 5 minutes | See the threshold note below. |

## Why the scrape alerts exist alongside the health alerts

The `*ServiceDown` rules match `<svc>_health_status == 0`, a metric the service
exports about itself. When the container stops, that series **disappears** — it
does not go to zero — so the expression matches nothing and the alert stays
silent through the exact outage it was written for. `up{job="..."} == 0` is
produced by Prometheus, not by the target, so it survives the target's death.

Keep both. They detect different failures, and neither subsumes the other.

## Applying a change to `alert_rules.yml`

**A rule change is not live until Prometheus is restarted.** Neither compose
file gives the `prometheus` service a `command:`, so `--web.enable-lifecycle` is
off and there is no `POST /-/reload` endpoint. `alert_rules.yml` is a bind
mount, so `docker compose up -d` sees no change to the service definition and
does not recreate the container. Editing the file alone leaves the old rules
loaded and the new ones silent — the exact failure #220 exists to eliminate.

```bash
docker compose restart prometheus

# Confirm the four scrape rules are loaded (expect: 4)
docker compose exec api_gateway \
  curl -s http://prometheus:9090/api/v1/rules | grep -o ScrapeDown | wc -l
```

Two details in that command are load-bearing. Prometheus is declared
`expose: "9090"` and publishes no host port, so `curl localhost:9090` from the
host is refused — the query has to run inside the compose network. And the
rules API returns one single-line JSON body, so `grep -c` counts that one line
and reports `1` no matter how many rules matched; `grep -o | wc -l` counts the
matches. Both mistakes read as "the rules did not load" when they did.

If that count is 0, the container is still running the previous rule file. If
it is anything other than 4, the file was edited without updating
`tests/test_service_down_alerting.py`, which asserts all four exist.

Enabling `--web.enable-lifecycle` would allow a reload without a restart, but it
also exposes a mutating endpoint on the Prometheus port; that is a deployment
decision for the operator, not a default.

## Threshold rationale

**Scrape alerts — `for: 2m` (gateway `1m`).** The scrape interval is 15s, so 2
minutes is eight consecutive failures: long enough to ride out a restart or a
single missed scrape, short enough that an operator hears about a dead model
service before more than a couple of conversations fail. The gateway gets 1
minute because its failure is a total outage.

**`GPUMemoryPressure` at 0.95 and `TranslationLatencyHigh` at 3s are inherited
values, not measured ones.** No baseline exists to justify either. #220 requires
recalibration "from observed baselines", and the catalogue
(`docs/operations/conversation-quality-kpis.en.md:279`) prescribes a two-to-four
week window. That window has not run yet.

Until it has, both stay as-is and are treated as unproven. Do not tune them from
a single incident. The observation window is tracked as part of the same
baselining that KPIs Q4 (delivery SLO breach rate) and R10 (SLO compliance) need
— one exercise, two consumers.

## Response

1. `docker compose ps` — is the container running?
2. `docker compose logs --tail=200 <service>` — model load failure, OOM, CUDA error?
3. `nvidia-smi` — is the GPU visible and does it have free memory?
4. `docker compose restart <service>`, then confirm the alert clears within one
   scrape interval plus the `for` duration.
5. If it recurs, capture the logs before restarting again and open an issue.

## Verification

These rules were verified on 2026-09-07 against Prometheus v3.13.1 with a 15s
scrape interval: the asr, translation and tts containers were each stopped and
observed across two rounds — translation first, then asr and tts together —
with the corresponding `*ScrapeDown` alert reaching state `firing` each time,
and each cleared after its container was restarted. With
`translation` stopped, `up{job="translation"}` read 0 while
`translation_health_status` was absent from the series entirely — confirming
directly that `TranslationServiceDown` had nothing to match, which is why both
rule kinds are kept. `APIGatewayScrapeDown` was not exercised this way — the
gateway is the shared local API and stopping it was not worth the disruption —
but its rule was confirmed loaded with `for: 1m` against an existing job. See
the issue-#220 thread for the full record. Re-verify after any change to
`monitoring/prometheus.yml` job names — an `up{job="asr"}` alert on a job that
no longer exists under that name is inert and silent.
