# Loki and Promtail ingestion protection

## Strategy

Promtail labels Docker streams, then drops the `loki` and `promtail` streams
in its pipeline. Loki query execution messages and Promtail retry messages
therefore cannot be pushed back to Loki. Application and platform container
logs remain collected normally.

## Alerts

Prometheus scrapes Promtail internally at `promtail:9080`. The following
warning alerts identify log-loss risk:

- `PromtailPushRateLimited`: Loki has returned HTTP 429 continuously for five
  minutes.
- `PromtailDroppedEntries`: Promtail has reported dropped entries.

Investigate the container labels and the Loki ingestion rate limit before
raising the limit. Do not re-enable Loki or Promtail container collection;
their logs are intentionally available through `docker logs`.

## Deployment verification

After applying the production Compose definition, run:

```bash
source scripts/lib/production-common.sh
production_compose up -d --no-deps --force-recreate loki promtail prometheus
production_compose exec -T promtail wget -qO- http://127.0.0.1:9080/metrics | grep '^promtail_'
production_compose exec -T prometheus wget -qO- 'http://127.0.0.1:9090/api/v1/query?query=up%7Bjob%3D%22promtail%22%7D'
```

The immediate deployment baseline is `up{job="promtail"} == 1` and no active
`PromtailPushRateLimited` or `PromtailDroppedEntries` alert. During a later,
ordinary one-hour dashboard-use sample, both counters must remain at zero.
That sample is a non-blocking operational check: the fix is complete once the
configuration is deployed and the immediate baseline passes; the sample does
not keep issue #352 open.
