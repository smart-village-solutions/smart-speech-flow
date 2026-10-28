# Recording Mode Cutover Runbook

## Scope

The deploy of #615 replaces the consent-gated `ask` storage with recording mode.
From then on a conversation outside a recording leaves nothing behind: Redis
keeps nothing on disk, delivery audio lives on the gateway's `/tmp/audio`
tmpfs, and the gateway writes no core dumps. Conversations stored under `ask`
are purged in the same deploy (decided 2026-10-26): the `audio-data` volume and
the Redis data volume are removed. Existing backups are not rewritten; they age
out under their own tiers, and new backups no longer contain Redis or audio.

## Before you start

- The archive (archive-storage-deployment.md) and the recording keys
  (recording-keys-deployment.md) are in place, so recording can start right
  away.
- **Studio's guest explanation texts no longer offer to store conversations.**
  Until #615 they described the `ask` storage question ("up to 180 days"); with
  the question gone that wording is false. Check every guest language's
  explanation in Studio before the deploy.
- Swap: the gateway never swaps (`memswap_limit` equals its memory limit), so
  its tmpfs and heap stay in RAM. Redis and ASR have no such limit: on a host
  with swap (`swapon --show` lists a device; production had 32 GiB in
  2026-10) their pages can be written to it. Turn swap off, or accept that
  before the deploy.

## Every command names its stack

Production compose commands go through `production_compose` from
`scripts/lib/production-common.sh`; a bare `docker compose` on the production
host targets the development stack.

    source scripts/lib/production-common.sh

## Step 1 — No live conversations

The cutover ends every live conversation: Redis restarts without its data.

    production_compose exec -T redis redis-cli --scan --pattern '*:v2:tenant:*:active-admin'

Expected: nothing printed. Otherwise wait, or agree a window with the tenants.
The check and the deploy are separate steps, so a conversation can still start
in between; keep the gap short, ideally inside an agreed window.

## Step 2 — Deploy

Build, pin and apply the gateway, frontend and compose change as for any
release (`scripts/deploy-production.sh --check`, then `--apply`). The apply
recreates Redis without a volume, the gateway with the tmpfs mounts, the
`ulimits` and `SSF_AUDIO_BASE_DIR=/tmp/audio`, and ASR with a tmpfs `/tmp`.

## Step 3 — Purge the `ask` data

The two volumes are no longer mounted by any container. Confirm, then remove
them:

    docker ps -a --filter volume=ssf-backend_redis-data --filter volume=ssf-backend_audio-data
    docker volume rm ssf-backend_redis-data ssf-backend_audio-data

Expected: the first command lists no container, the second prints both names.
This deletes every conversation stored under `ask`, audio and text alike.

## Step 4 — Verify

    production_compose exec -T redis redis-cli CONFIG GET save
    production_compose exec -T redis redis-cli CONFIG GET appendonly
    production_compose exec -T api_gateway sh -c 'ulimit -c; df -h /tmp /tmp/audio | tail -2'
    production_compose exec -T api_gateway cat /sys/fs/cgroup/memory.swap.max
    production_compose exec -T asr sh -c 'df -h /tmp | tail -1'
    swapon --show
    docker volume ls --filter name=ssf-backend_audio-data --filter name=ssf-backend_redis-data -q

Expected: `save` empty, `appendonly no`, `0`, a 256 MiB and a 1 GiB `tmpfs`
in the gateway, `0` for the gateway's swap, a 256 MiB `tmpfs` in ASR, no swap
on the host (or the accepted exception), and no volume listed. Then hold one conversation, end it, and check that its
audio is gone:

    production_compose exec -T api_gateway sh -c "find /tmp/audio/v2 -name '*.wav' | wc -l"

Expected: `0` once no conversation is running. The tester release check
(tester-release-check.md) runs the same checks with four conversations.

## Rollback

The purge cannot be undone, and a rollback does not need it undone: the earlier
gateway starts with an empty audio volume and an empty Redis. Roll back the
images and compose as usual, then restart Redis as well (`production_compose
restart redis`): the earlier gateway cannot read recording states this one
wrote, and Redis without persistence comes back empty. Both end live
conversations, so roll back while none runs.
