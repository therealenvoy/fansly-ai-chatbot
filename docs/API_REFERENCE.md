# OnlyFansAPI Fansly contract

This project sends all Fansly traffic through OnlyFansAPI's Fansly product.
Do not use the retired `v1.apifansly.com` endpoints, `x-api-key` authentication,
or their request/response shapes.

Canonical documentation:

- https://docs.onlyfansapi.com/api-reference/fansly
- https://docs.onlyfansapi.com/api-reference/fansly/chats/list-chats
- https://docs.onlyfansapi.com/api-reference/fansly/chat-messages/send-chat-message
- https://docs.onlyfansapi.com/api-reference/fansly/media/upload-media
- https://docs.onlyfansapi.com/api-reference/fansly/earnings/list-wallet-transactions

The Fansly surface is currently closed beta and may change. Verify the current
documentation before adding or changing a provider request.

## Connection

- Base URL: `https://app.onlyfansapi.com`
- Authentication: `Authorization: Bearer <FANSLY_API_KEY>`
- Account IDs are resolved from `GET /api/fansly/accounts`.
- Fansly account IDs use the `fansly_acct_` form.

## Chats

```text
GET /api/fansly/{fanslyAccount}/chats
```

Supported query fields used by the bot:

- `limit`: 1-100
- `offset`: non-negative pagination offset
- `order`: `newest`, `oldest`, or `unread`

Important response fields:

- `data.data[].groupId`
- `partnerAccountId`
- `unreadCount`
- `lastMessageId`
- `lastUnreadMessageId`
- `data.hasMore`

## Chat messages

```text
GET /api/fansly/{fanslyAccount}/chats/{chat_id}/messages
POST /api/fansly/{fanslyAccount}/chats/{chat_id}/messages
```

The documented send body supports:

```json
{
  "text": "Message text",
  "mediaFiles": ["fansly_media_..."],
  "replyToMessageId": "optional-message-id"
}
```

`mediaFiles` must contain `fansly_media_` IDs from the Fansly upload endpoint.

The current documented Fansly send body does **not** expose price, paywall,
`requirePurchase`, access-rule, or preview fields. The implementation therefore
rejects paid/PPV sends before making an HTTP request. It must not borrow the
OnlyFans product's PPV fields or the retired apifansly.com request shape.

## Media upload

```text
POST /api/fansly/{fanslyAccount}/media/upload
```

Provide exactly one of `file` or `file_url`. The synchronous response returns a
reusable `prefixed_id` beginning with `fansly_media_`. Large asynchronous
uploads return a polling URL and require a separate completion workflow.

## Wallet ledger

```text
GET /api/fansly/{fanslyAccount}/earnings/transactions
```

The endpoint accepts `limit` (1-100) and `offset`. It returns transaction IDs,
type codes, millidollar amounts, balances, statuses, and timestamps.

The documented row does not identify a fan or purchased message. Wallet rows
are therefore stored as aggregate provider transactions and never used to:

- increment a fan's purchase count;
- advance a PPV sequence;
- trigger aftercare;
- claim that a particular fan unlocked a message.

An attributed purchase requires a separate verified event containing the fan
ID and exact provider message ID.
