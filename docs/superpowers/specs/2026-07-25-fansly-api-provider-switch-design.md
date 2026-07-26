> **Superseded:** This historical design guessed paid-message fields that are
> not present in the current OnlyFansAPI Fansly contract. Use
> `docs/API_REFERENCE.md` and `docs/PURCHASE_AND_PPV.md` as the authoritative
> integration contract.

# Design: Switch Fansly API Provider (apifansly.com → OnlyFansAPI's Fansly API)

## Objective

apifansly.com's credits are depleted (402 on every call), so the bot currently runs with `bot.enabled=False` at startup — no polling, no replies. Switch the live provider to OnlyFansAPI's Fansly product (marketed at fansly-api.com, actual API host `app.onlyfansapi.com`), which the user has an active, funded key for, without losing the ability to fall back to apifansly, and without accidentally burning through credits via naive polling.

## Confirmed API facts

Verified directly against OnlyFansAPI's public (if closed-beta) docs at `docs.onlyfansapi.com/api-reference/fansly` — not guessed.

- **Base URL**: `https://app.onlyfansapi.com`
- **Auth**: `Authorization: Bearer <token>` header (apifansly used `x-api-key`)
- **Account ID**: not user-supplied. `GET /api/fansly/accounts` returns the connected account's `fansly_acct_XXX` ID (assumes the Fansly account is already connected via the OnlyFansAPI dashboard — confirmed true for this user).
- **Credit cost**: 1 credit per call for chats/messages/send/reactions; media upload billed per MB.
- **Endpoints confirmed** (real request/response shapes captured from live docs):
  - `GET /api/fansly/{fanslyAccount}/chats` — list chats, response shape nearly identical to apifansly's (`data.data[]`, `aggregationData`)
  - `GET /api/fansly/{fanslyAccount}/chats/{chat_id}/messages` — list messages
  - `POST /api/fansly/{fanslyAccount}/chats/{chat_id}/messages` — send message/PPV. Body uses `text` (not `content`); PPV uses `mediaFiles: [fansly_media_id]`, `requirePurchase: true`, `price` in millidollars (1000 = $1.00), vs. apifansly's `mediaIds`/`access_type`/dollar-float `price`.
  - `POST /api/fansly/{fanslyAccount}/chats/{chat_id}/messages/{message_id}/reactions` — like/react, requires `type` int (1=heart, use as the "like" equivalent)
  - `POST /api/fansly/{fanslyAccount}/media/upload` — multipart or `file_url`, returns `fansly_media_XXX`
  - `GET /api/fansly/accounts` — list connected accounts, source of `fansly_acct_ID`

- **Confirmed gaps** (not available on this provider in closed beta): no vault/album endpoints, no earnings endpoints. `list_albums`/`get_album_media` (used by mass-messaging PPV ladders) and earnings calls (used by the KPI dashboard) have no equivalent yet.
- **Webhooks investigated and rejected for this build**: OnlyFansAPI's webhook system is real (HMAC-signed, `messages.received` etc.) but every documented event uses OnlyFans account IDs (`acct_123`) and OnlyFans-shaped payloads. No Fansly-scoped webhook event exists in the docs. Building a receiver now would have nothing to subscribe to — revisit if/when OnlyFansAPI extends webhooks to Fansly.

## Cost analysis

Credit cost is 1/call. The bot's current polling loop (`POLL_INTERVAL=30s`, no idle backoff — only the existing failure-backoff at `main.py:183-190` reacts to errors) would call `list_chats` ~2,880 times/day = ~86,400 credits/month from polling alone, before any `list_messages` fan-out or replies. That exceeds an entire month's Basic-tier budget (20,000 credits/$69/mo) in ~5-6 hours.

Decision: **idle-adaptive polling**, base interval raised to 60s, backing off exponentially (cap `IDLE_BACKOFF_MAX`, default 600s) after consecutive cycles with zero unread chats, resetting to the fast interval the instant any chat shows unread activity. Combined with only calling `list_messages` for chats with `unread_count > 0` (free info already in the `list_chats` response), this keeps overhead in a sane range while keeping response latency low during real conversations — the case that actually matters for PPV conversion.

## Architecture

```
src/
  fansly_client.py         MODIFY — extract FanslyApiClient(ABC), rename current impl to ApifanslyClient
  fansly_api_client.py     NEW    — FanslyApiClientImpl (OnlyFansAPI's Fansly product)
  client_factory.py        NEW    — get_fansly_client() reads FANSLY_PROVIDER env var
  bot.py                   MODIFY — unread_count pre-filter before list_messages fan-out;
                                     poll_and_process() returns whether any unread was found;
                                     otherwise unchanged — still only depends on the ABC
  main.py                  MODIFY — idle-adaptive backoff loop; client_factory instead of
                                     constructing FanslyClient directly; new env var names
tests/
  test_fansly_api_client.py   NEW — TDD tests using real captured response shapes
```

- `FanslyApiClient(ABC)`: `get_all_chats`, `list_messages`, `send_message`, `send_ppv`, `like_message`, `upload_media`, `close`, plus `list_albums`/`get_album_media` (present on the interface; `FanslyApiClientImpl` raises `NotImplementedError` for these until OnlyFansAPI ships vault support for Fansly).
- `ApifanslyClient`: today's `FanslyClient`, renamed, logic unchanged.
- `FanslyApiClientImpl`: new class. `httpx.Client(base_url="https://app.onlyfansapi.com")`, `Authorization: Bearer` header, resolves and caches `fansly_acct_ID` once at construction via `GET /api/fansly/accounts` (not refetched per poll).
- `client_factory.get_fansly_client()`: single function, reads `FANSLY_PROVIDER` (`apifansly` default, `fanslyapi` to switch), builds the right client from env vars. Only place that references both concrete classes.

## Data flow

**Startup** (~1-2 credits total): factory resolves provider → if `fanslyapi`, one `GET /api/fansly/accounts` call, cached for the process lifetime.

**Per poll cycle**:
1. `client.get_all_chats()` — 1 call (more if paginated)
2. In-process filter: `[c for c in chats if c.unread_count > 0]` — zero cost
3. `list_messages` only for chats surviving the filter
4. Idle-adaptive interval: consecutive empty cycles → interval doubles up to `IDLE_BACKOFF_MAX`; any unread found → reset to fast `POLL_INTERVAL`
5. Sends/reactions/PPVs cost 1 credit each — unavoidable, that's real bot activity, not overhead

**Rollback**: `FANSLY_PROVIDER=apifansly` on Railway + redeploy, zero code changes, assuming apifansly credits get topped up again.

## Error handling

`FanslyApiClientImpl._request()` mirrors `ApifanslyClient`'s existing retry/backoff structure (429 → respect `Retry-After`, 5xx → exponential retry, timeouts → retry, 401/403 → `AuthError`), pointed at the new base URL and auth scheme.

## Testing strategy

TDD per the existing `tasks/provider-switch-spec.md`. Every mocked response body in the new tests uses the **real shapes captured from the live docs during this design session** (list chats, list messages, send message, add reaction, upload media, list accounts) — not invented data. Existing test suite (`test_bot.py`, `test_settings.py`, full suite) must continue to pass unmodified, since `bot.py` only depends on the ABC.

## Env var changes (Railway)

- Remove: `APIFANSLY_API_KEY` (if separately set — code already falls back from `FANSLY_API_KEY`)
- Add: `FANSLY_PROVIDER=fanslyapi`, `FANSLY_API_KEY=<new Bearer token>` (secret)
- `FANSLY_ACCOUNT_ID` becomes unused for the `fanslyapi` provider path (resolved via API instead) — keep it set for `apifansly` rollback compatibility
- New: `IDLE_BACKOFF_MAX` (default 600), `POLL_INTERVAL` default changes from 30 to 60

## Out of scope for this build

- Webhook receiver (no Fansly-scoped events exist yet on this provider)
- Vault/album support for the new provider (`NotImplementedError` until OnlyFansAPI ships it)
- Earnings/KPI dashboard data for the new provider (same reason)
