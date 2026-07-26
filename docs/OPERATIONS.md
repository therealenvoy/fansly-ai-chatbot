# Production operations

## Probes and monitoring

- `/health` is public liveness only. It proves that the HTTP process responds.
- `/ready` is public and returns `503` until the database accepts `SELECT 1`.
  Railway deploy health checks and the container health check use this route.
- `/api/operations` requires dashboard Basic Auth. It reports database
  readiness, provider state, bot/launch state, durable inbox/outbox counts, and
  polling timestamps/failures. It never returns credentials.
- Railway deployment health checks run during deployment, not continuously.
  Configure an external HTTPS uptime check against `/ready`; alert on two
  consecutive failures. Also alert when `/api/operations` shows a growing
  `outbox_delivery_unknown` or `inbound_failed` count.

## Backup and restore

Production state lives in Railway PostgreSQL. Persona and brand files may live
on the mounted `/data` volume.

1. Enable daily and weekly Railway backups before launch and verify the
   retention shown in the Backups tab. Consider PostgreSQL point-in-time
   recovery when the required recovery point is shorter than one day.
2. Before a schema migration or broad rollout, create an on-demand backup.
3. Monthly, perform a restore drill. Prefer point-in-time recovery because it
   creates a sibling PostgreSQL service without modifying the source. Native
   volume backups can only restore in the same project and environment, so do
   not initiate that workflow against live production without a maintenance
   plan and verified copy.
4. Run `alembic upgrade head`, then verify `/ready`, dashboard reads, and inbox,
   outbox, settings, conversations, purchases, and sequence progress.
5. Record the backup timestamp, restore duration, row-count checks, and operator.
6. Back up the app service's `/data/config` volume separately after persona or
   brand changes; a backup of the PostgreSQL service's volume does not include
   the app service's volume.

Never test a restore by overwriting production.

## Controlled launch

Required production variables:

```text
FANSLY_PROVIDER=fanslyapi
CONTROLLED_LAUNCH=true
BOT_ENABLED_DEFAULT=false
FAN_ALLOWLIST=<one or more exact Fansly account IDs>
MAX_MESSAGES_PER_POLL=5
```

Run this inside the configured deployment environment:

```bash
python -m src.launch_preflight
```

The check is read-only and does not print secrets. Then:

1. Confirm CI core and PostgreSQL jobs pass.
2. Confirm `/ready` returns `200` and `/api/operations` is healthy.
3. Keep the bot disabled and add one internal/pilot fan account ID.
4. Enable it from the dashboard. The server rejects enabling when the controlled
   launch allowlist is empty.
5. Verify one inbound message, one outbox send, and the returned provider message
   ID. Check for `delivery_unknown` before expanding.
6. Expand the allowlist gradually. Each allowlist has its own poll cursor so a
   newly added pilot is scanned without reprocessing another pilot's history.

## Rollback

1. Disable the bot in the dashboard first; this is persisted in PostgreSQL.
2. If the dashboard is unavailable, set `BOT_ENABLED_DEFAULT=false` and clear
   `FAN_ALLOWLIST`, then redeploy.
3. Roll Railway back to the last known-good image.
4. Do not automatically resend `outbox_delivery_unknown`; reconcile it against
   the provider first because a timed-out send may have succeeded.
5. Restore PostgreSQL only for confirmed data corruption. A code rollback does
   not normally require a database restore.
