# apifansly.com API — Complete Reference for Fansly AI Chatbot

> Last updated: 2026-07-24 · Docs: https://docs.apifansly.com

## Quick Reference

- **Base URL:** `https://v1.apifansly.com/api/fansly`
- **Auth Header:** `x-api-key: YOUR_API_KEY`
- **Content-Type:** `application/json`
- **Response Format:** `{statusCode, message, data, timestamp}`

## Plans

| Plan | Price | Accounts | Credits/Mo | RPM |
|------|-------|----------|------------|-----|
| Free | $0 | 1 | 30 | 100 |
| Starter | $49 | 2 | 24,000 | 600 |
| Pro | $129 | 5 | 60,000 | 1,000 |
| Enterprise | Custom | Custom | Custom | Unlimited |

## Credit System
- 1 Standard Request = 1 Credit
- 1 Media MB = 2 Credits
- 80 Webhook Events = 1 Credit
- Every 80KB of response data = 1 Credit
- Monthly reset, no rollover

## Rate Limits
- Per-minute sliding window
- Response headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Plan`, `X-RateLimit-Retry-After`
- 429 on exceed → implement exponential backoff

---

## MESSAGING ENDPOINTS (Critical for Bot)

### List Chats
```
GET /{account_id}/chats?filter=all&sort=newest&cursor=NEXT_CURSOR&search=QUERY&subscriptionTierId=TIER_ID
```
Query params: `filter` (all/vips/followers/subscribers), `sort` (newest/oldest/unread), `cursor`, `search`, `subscriptionTierId`

Response highlights: `data.data.response.data[].groupId` (this is your chat_id), `.partnerUsername`, `.unreadCount`, `.lastMessageId`, `.aggregationData.accounts[].displayName`, `.avatar`

### List Chat Messages
```
GET /{account_id}/chats/{chat_id}/messages?limit=10&cursor=CURSOR
```
`limit`: min 1, max 10. `cursor`: for pagination (found at `response.cursor`)

Response highlights: `messages[].id`, `.content`, `.senderId`, `.createdAt` (unix), `.attachments`, `.totalTipAmount`, `accountMedia[].price`, `.access` (bool), `.media.locations[].location` (CDN URL)

### Send Message (THE KEY ENDPOINT)
```
POST /{account_id}/chats/{chat_id}/messages
```
Body:
```json
{
  "content": "Message text here",
  "mediaIds": [{"mediaId": "MEDIA_ID", "previewId": null}],
  "access_type": ["ppv"],
  "price": 15.00
}
```

**Media Permissions:** `access_type` can be: `ppv`, `subscription`, `follow`, `list`, `limited_time` (single string or array)
- `price`: dollar amount for PPV
- `subscriptionTierId` / `subscriptionTierName`: for tier-locked
- `listId` / `listLabel`: for list-restricted
- `validBefore` / `validAfter`: epoch timestamps for time-limited
- `permissions[]`: array of custom rules — OR'd together (fan needs to satisfy ANY one rule)

**PPV limits:** Max $200 per message on Fansly platform.

**Response:** `201 Created` with message ID, timestamps, attachment details

### Like Message
```
POST /{account_id}/chats/{chat_id}/messages/{message_id}/like
```

---

## EARNINGS ENDPOINTS

### Earning Statistics
```
GET /{account_id}/earnings
```
Response: `{pendingBalance: 529}` (in dollars)

### List Transactions
```
GET /{account_id}/earnings/transactions?before=TIMESTAMP_MS&after=TIMESTAMP_MS&limit=20&offset=0
```

### Fan Earnings (LTV tracking!)
```
GET /{account_id}/earnings/fans/{fan_id}
```
Response: `[{year, month, totalGross, totalNet}]` — monthly breakdown

---

## MEDIA ENDPOINTS

### Upload Media (2-step)
**Step 1:** `POST /{accountId}/media/upload` (multipart/form-data, field: `file`)
→ Returns `{jobId}`

**Step 2:** `GET /media/upload/{jobId}/status`
→ Poll until `state: "completed"`, then grab `result.mediaId`

### Download Media
```
POST /media/download
Body: {"cdnUrl": "https://cdn3.fansly.com/..."}
```
→ Returns raw binary (stream for large files, 60-120s timeout for video)

---

## VAULT ENDPOINTS

### List Albums
```
GET /{accountId}/vault/albums
```
Response: `{albums: [{id, title, itemCount, type, ...}]}`

### Get Album Media
```
GET /{accountId}/vault/albums/{albumId}/media?cursor=CURSOR
```
Response: array of media items with `mediaId`, `previewId`, `price`, `media.locations[]`

---

## ANALYTICS ENDPOINTS

### Profile Statistics
```
GET /{accountId}/analytics/profilestats?beforeDate=MS&afterDate=MS&period=86400000&year=2026&month=7
```
Covers: media views, avg engagement time, unique viewers, profile visits, traffic sources, FYP tags, top media

### Media Statistics
```
GET /{accountId}/analytics/media/{mediaOfferId}?beforeDate=&afterDate=&period=
```

---

## WEBHOOKS
- Register URL in Developer Console
- Receives POST with JSON event payload
- Must validate cryptographic signature
- Return 200 OK promptly
- Events: new messages, subscriptions, tips, purchases

---

## MESSAGE FORMATTING
- **NO markdown** — `**bold**`, `*italic*` render as raw text
- Plain text + emojis ✅
- Hashtags `#tag` → auto-linked
- URLs → auto-linked
- Line breaks: `\n`
- Unicode bold/italic generators work (e.g., `𝗧𝗵𝗶𝘀`, `𝘛𝘩𝘪𝘴`)

---

## ACCOUNT CONNECTION
- Automated login via [Fansly API Console → Accounts](https://app.apifansly.com/accounts)
- Enter email + password + proxy country
- Supports 2FA (prompted during connection)
- Each connected account gets an `account_id`

---

## ERROR CODES
| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 400 | Bad Request |
| 401 | Unauthorized (bad API key) |
| 403 | Forbidden |
| 404 | Not Found |
| 429 | Rate Limited |

---

## BOT INTEGRATION NOTES

### Chat Loop:
1. `GET /{account_id}/chats?filter=all&sort=newest` → get all chats
2. `GET /{account_id}/chats/{chat_id}/messages?limit=10` → read last 10 messages per chat
3. Process messages through our 17-system pipeline (persona, funnel, scripts, NLP, etc.)
4. `POST /{account_id}/chats/{chat_id}/messages` → send reply (text only or with PPV media)

### Sending PPV:
1. Upload media → `POST /media/upload` → poll status → get `mediaId`
2. Send message with `mediaIds`, `access_type: ["ppv"]`, `price: X.XX`

### Fan LTV Tracking:
- Use `GET /{account_id}/earnings/fans/{fan_id}` to get per-fan earnings
- Feed into our `FanNote.total_spent` and `TierClassifier`

### Rate Limit Safety:
- Pro plan: 1000 RPM = ~16 req/sec → safe for real-time chat
- Batch list-chats every 30s, not every message
- Cache chat lists and fan notes between polls