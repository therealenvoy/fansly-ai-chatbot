# How Might We: Eliminate polling costs while maintaining real-time responsiveness across 4+ creator accounts?

Current problem: Polling costs 99.6% of credits. Every 30 seconds, we call the API even when nothing happens. At 4 accounts, this is ~345,600 calls/month.

## 8 Architectural Variations

### Variation 1 — Pure Webhook Receiver
Single `/webhook` endpoint. Fansly pushes events. Bot processes immediately. No polling.
- **Pros:** Zero idle cost, instant responses, simplest architecture
- **Cons:** No delivery guarantee — if webhook fails, message is missed entirely

### Variation 2 — Webhook + Heartbeat Polling
Webhooks for real-time. A slow heartbeat (300s) catches missed events.
- **Pros:** Delivery guarantee (<5min latency on failure), best of both
- **Cons:** Minimal remaining credit burn (~300 calls/day)
- **Industry standard for chat systems**

### Variation 3 — Webhook with Processing Queue
Webhooks write to an in-memory queue (asyncio.Queue). Worker processes one at a time.
- **Pros:** Backpressure handling, rate limiting, ordered processing
- **Cons:** Queue loss on crash (use Redis for persistence at scale)

### Variation 4 — Multi-Account Event Router
One webhook URL for all accounts. Payload includes `account_id`. Routes to correct `FanslyBot` instance.
- **Pros:** Single endpoint to configure, scales to N accounts
- **Cons:** Need to validate which account the event is for

### Variation 5 — Event Type Dispatcher
Parse event_type from webhook payload: `new_message`, `new_subscriber`, `tip_received`, `purchase`. Route to specialized handlers.
- **Pros:** Can trigger re-engagement, aftercare, reciprocity from subscription/tip events too
- **Cons:** More complex handler logic

### Variation 6 — Dual-Mode Processing
Fan sends message → webhook fires → bot replies within 2 seconds.
Separate cron at 15min intervals handles: churn checks, re-engagement, mass messaging, KPI updates.
- **Pros:** Chat is real-time, periodic tasks don't interfere
- **Cons:** Two systems to maintain

### Variation 7 — Railway Native Endpoint
Use Railway's built-in public URL as the webhook receiver. Attach to existing dashboard FastAPI server.
- **Pros:** No new infrastructure, already running
- **Cons:** Dashboard server is single-threaded (need threading fix first)

### Variation 8 — Stateless Webhook Handler
Webhook handler is a standalone module with minimal dependencies. Zero state — just receives event, delegates to FanslyBot, returns 200.
- **Pros:** Can be tested independently, deploy as separate service if needed
- **Cons:** Duplicates some bot state

## Converged Direction

**Variation 2 + 4 + 6 combined = "Event-Driven Bot with Heartbeat"**

This is the architecture:
```
                    ┌─────────────────────────────┐
                    │   apifansly.com Webhooks     │
                    │   (new_message, sub, tip)     │
                    └──────────┬──────────────────┘
                               │ POST /webhook
                               ▼
                    ┌─────────────────────────────┐
                    │   WebhookReceiver            │
                    │   - validate HMAC            │
                    │   - parse event_type         │
                    │   - route to correct account │
                    └──────────┬──────────────────┘
                               │
                    ┌──────────▼──────────────────┐
                    │   FanslyBot._process_event() │
                    │   - read message (1 credit)  │
                    │   - generate reply           │
                    │   - send reply (1 credit)    │
                    │   - persist to memory        │
                    │   - run funnel logic         │
                    └─────────────────────────────┘
                    
                     ┌───────────────────────────┐
                     │   Heartbeat Poll (300s)    │
                     │   - catch missed webhooks  │
                     │   - fan re-engagement      │
                     │   - churn checks           │
                     │   - KPI updates            │
                     └───────────────────────────┘
```

## Key Architectural Decisions

1. **Webhook endpoint**: Add `/webhook` route to existing dashboard FastAPI server
2. **Event format**: Expect `{account_id, event_type, data: {chat_id, fan_id, message_id, content?, timestamp}}`
3. **Processing**: Extract `_process_single_message()` from bot.py — process one chat without polling all
4. **Heartbeat**: Reduce current poll loop to 300s interval, skip if no active sessions
5. **Multi-account**: `BotManager` dict of `account_id → FanslyBot`, created at startup from env config

## Assumptions to Validate

- [ ] apifansly.com actually sends message CONTENT in webhooks (vs just notification)
- [ ] Webhooks are reliable enough to not miss events (>99% delivery)
- [ ] Railway can receive webhooks (it's a public URL — yes)
- [ ] Webhook includes `account_id` in payload (needed for multi-account routing)
- [ ] HMAC/API key verification mechanism exists