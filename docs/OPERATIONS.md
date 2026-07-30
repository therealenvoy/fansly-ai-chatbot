# Production operations

## Probes and monitoring

- `/health` is public liveness only. It proves that the HTTP process responds.
- `/ready` is public and returns `503` until the database accepts `SELECT 1`.
  Railway deploy health checks and the container health check use this route.
- `/api/operations` requires dashboard Basic Auth. It reports database
  readiness, provider state, bot/launch state, durable inbox/outbox counts, and
  polling timestamps/failures. It also reports the last accepted message
  webhook time and total accepted webhook events. Its `crm_sync` section reports discovered,
  complete, pending, and failed histories plus stored message count. It never
  returns credentials or message contents.
- Fansly inbound messages enter through the secret APIFansly route
  `/webhooks/apifansly/<token>`. The route rejects another connected account
  or a creator-authored received event and inserts one idempotent durable inbox
  row.
- Reply workers drain that queue independently from provider reconciliation,
  CRM history imports, and proactive scans. Work for one fan remains ordered;
  different fans can run concurrently. Routine and unread-chat polling remain
  disabled.
- Railway deployment health checks run during deployment, not continuously.
  `.github/workflows/production-monitor.yml` checks `/ready` every 15 minutes
  and fails only after two consecutive failed probes. Scheduled workflows run
  from GitHub's default branch, so the monitor is not active until this
  workflow is present there and Actions notifications are enabled.
- Review `/api/operations` for a growing `outbox_delivery_unknown` or
  `inbound_failed` count. This authenticated operational check is deliberately
  not placed in GitHub Actions because the dashboard password should not be
  duplicated into another secret store.

## Backup and restore

The current production `DATABASE_URL` points to Neon PostgreSQL. The Railway
app service also has a separate volume mounted at `/data` for persona and brand
files. These are two independent backup domains: a Railway volume backup does
not protect Neon, and a Neon restore does not protect `/data`.

### Neon PostgreSQL

1. In the Neon console, open **Backup & Restore** and verify the production
   branch's instant-restore window.
2. On plans that support scheduled snapshots, configure daily and weekly
   snapshots with explicit retention. Before a schema migration or broad
   rollout, create an on-demand snapshot.
3. Monthly, restore to a new temporary branch and run `alembic upgrade head`.
   Verify `/ready`, dashboard reads, inbox, outbox, settings, conversations,
   purchases, and sequence progress against that isolated branch.
4. Never finalize a restore onto the production branch as a drill. Use an
   isolated restore branch, record row-count checks, then delete it after the
   drill.

### Railway `/data` volume

1. In `fansly-bot / sunny-charm / Backups`, enable daily and weekly schedules
   for `sunny-charm-volume`.
2. Create an on-demand volume backup after persona or brand changes.
3. Railway volume restores are limited to the same project and environment and
   replace the mounted volume after staged changes are deployed. Test restores
   only under a maintenance plan and never by overwriting live production.
4. Record each backup timestamp, retention, restore duration, verification
   result, and operator.

Never test a restore by overwriting production.

## Webhook-first conversation runtime

Required APIFansly configuration:

```text
FANSLY_PROVIDER=apifansly
APIFANSLY_API_KEY=<APIFansly API key>
FANSLY_ACCOUNT_ID=<connected APIFansly account ID>
APIFANSLY_WEBHOOK_TOKEN=<at least 32 random characters>
APIFANSLY_WEBHOOK_ENABLED=true
RECOVERY_RECONCILIATION_ENABLED=false
REPLY_WORKER_COUNT=2
REPLY_WORKER_IDLE_SECONDS=1
REPLY_DELAY_MIN_SECONDS=5
REPLY_DELAY_MAX_SECONDS=25
PROCESSING_RETRY_BASE_SECONDS=5
PROCESSING_RETRY_MAX_SECONDS=60
CRM_SYNC_ENABLED=false
```

In the APIFansly developer console, register exactly this credential-bearing
endpoint:

```text
https://<RAILWAY_PUBLIC_DOMAIN>/webhooks/apifansly/<APIFANSLY_WEBHOOK_TOKEN>
```

Select only `messages.received`, `messages.sent`, and `ppv.purchased`. APIFansly
does not currently document a webhook-management API, so registration is
managed in its developer console. Confirm `webhook_events_received` advances
in `/api/operations`. Do not enable routine recovery polling as a substitute
for a broken webhook.

## Controlled launch

Required production variables:

```text
FANSLY_PROVIDER=apifansly
APIFANSLY_API_KEY=<APIFansly API key>
FANSLY_ACCOUNT_ID=<connected fansly_acc_... account>
APIFANSLY_WEBHOOK_TOKEN=<at least 32 random characters>
APIFANSLY_WEBHOOK_ENABLED=true
CONTROLLED_LAUNCH=true
BOT_ENABLED_DEFAULT=false
FAN_ALLOWLIST=<one or more exact Fansly account IDs>
MAX_MESSAGES_PER_POLL=5
RECOVERY_RECONCILIATION_ENABLED=false
CRM_SYNC_ENABLED=false
```

Normal inbound replies are webhook-driven and consume no unread-chat listing
credits. Historical CRM backfill is a separate explicit operation and remains
disabled in normal production.

The APIFansly account must be connected in its console before launch. Startup
must resolve the native Fansly creator ID from the configured
`fansly_acc_...` account.

Create one APIFansly webhook for `messages.received`, `messages.sent`, and
`ppv.purchased`:

```text
https://<RAILWAY_PUBLIC_DOMAIN>/webhooks/apifansly/<APIFANSLY_WEBHOOK_TOKEN>
```

Treat the entire URL as a credential. The application does not log HTTP
requests, but the token should still be rotated if it is exposed. APIFansly
also issues a signing secret; its public documentation does not currently
specify the signature header or algorithm, so the application uses the
high-entropy route token and will fail launch without it.

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
5. With the internal fan, verify one inbound reply and one low-price locked PPV
   using vault-selected media. Buy it from the controlled fan. Confirm the
   outbox has both provider IDs, the `ppv.purchased` event creates one purchase
   row, the sequence advances once, and the duplicate event is idempotent.
   Check for `delivery_unknown` before expanding.
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
