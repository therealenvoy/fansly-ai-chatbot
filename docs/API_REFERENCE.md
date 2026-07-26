# Fansly provider contracts

Fully automated paid PPV uses APIFansly. OnlyFansAPI's Fansly beta remains an
explicit fallback for free text/media, but the launch guard refuses to enable
it because it does not expose paid messages or vault albums.

Canonical APIFansly documentation:

- https://docs.apifansly.com/api-reference/account/get-current-account
- https://docs.apifansly.com/api-reference/chats/list-chats
- https://docs.apifansly.com/api-reference/chat-messages/list-chat-messages
- https://docs.apifansly.com/api-reference/chat-messages/send-message
- https://docs.apifansly.com/api-reference/vault/list-vault-albums
- https://docs.apifansly.com/api-reference/vault/get-vault-album-media
- https://docs.apifansly.com/webhooks/webhook-events

## APIFansly connection

- Base URL: `https://v1.apifansly.com/api/fansly`
- Authentication: `x-api-key: <APIFANSLY_API_KEY>`
- Connected account: `FANSLY_ACCOUNT_ID` in `fansly_acc_...` form
- Creator identity: resolved from `GET /{account_id}/me`

## Chats and messages

```text
GET  /{account_id}/chats
GET  /{account_id}/chats/{chat_id}/messages
POST /{account_id}/chats/{chat_id}/messages
```

Chats use cursor pagination and `sort=newest|oldest|unread`. Chat-message pages
have a documented maximum of ten messages, so the adapter clamps larger caller
limits and follows the returned cursor.

Paid PPV send body:

```json
{
  "content": "Unlock this",
  "mediaIds": [
    {"mediaId": "MEDIA_ID", "previewId": "OPTIONAL_PREVIEW_ID"}
  ],
  "access_type": ["ppv"],
  "price": 25.0
}
```

Price is in dollars and must be between `$1` and `$500`. The adapter rejects
invalid media, price, and access combinations before a network request.

## Vault

```text
GET /{account_id}/vault/albums
GET /{account_id}/vault/albums/{album_id}/media
```

The dashboard follows bounded vault-media cursors, displays provider thumbnails
or video previews, and stores the selected `mediaId` plus optional `previewId`
on the sequence step.

## OnlyFansAPI fallback

OnlyFansAPI uses `https://app.onlyfansapi.com`, Bearer authentication, and
`FANSLY_API_KEY`. Its documented Fansly send body supports `text`,
`mediaFiles`, and `replyToMessageId`, but not paywall fields. Its capability
flags therefore keep paid PPV and vault-backed launch disabled.

## Purchase attribution

APIFansly's active `ppv.purchased` webhook contains:

- `data.orderId`: unique purchase ID;
- `data.accountMediaId`: the purchased account-media reference;
- `data.accountId`: exact fan ID;
- `data.correlationAccountId`: creator's native Fansly ID;
- `data.orderMetadata.accountMediaPrice`: price in cents.

The PPV send response's attachment `contentId` is stored as
`outbox_messages.provider_purchase_ref`. The webhook can therefore resolve the
exact sent outbox row and advance only its matching sequence step. Duplicate
`orderId` events are idempotent. Fan, creator, media-reference, and amount
mismatches fail closed.

Webhook endpoint:

```text
POST /webhooks/apifansly/{APIFANSLY_WEBHOOK_TOKEN}
```

The token must contain at least 32 high-entropy characters. This application
route token is separate from APIFansly's signing secret. APIFansly currently
documents that a signing secret is issued, but does not publish the signature
header or verification algorithm; do not invent one. Rotate the route token if
the endpoint URL is exposed, and add signature verification when the provider
publishes its contract.
