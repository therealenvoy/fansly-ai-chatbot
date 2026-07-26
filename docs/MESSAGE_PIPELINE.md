# Durable message pipeline

The production bot uses PostgreSQL as a durable inbox and outbox. Provider
polling, response decisions, and delivery are separate state transitions so a
restart cannot silently forget work or automatically send the same response
twice.

## Processing order

1. Fetch Fansly chats in `newest` order until the saved chat-head checkpoint.
2. Select chats with unread messages or a changed `lastMessageId`.
3. Fetch messages until the saved conversation checkpoint.
4. Sort provider messages by `(created_at, message_id)` ascending.
5. Insert fan messages into `inbound_messages`. The unique
   `(creator_id, platform_message_id)` constraint makes ingestion idempotent.
6. Claim the oldest nonterminal inbound row. PostgreSQL uses
   `FOR UPDATE SKIP LOCKED`; an earlier pending or processing row blocks newer
   rows so multiple workers cannot reorder sends.
7. Load the fan's persistent session and validate inbound content.
8. Generate, humanize, style, and validate one response.
9. Insert that approved typed response into `outbox_messages`, including its
   kind, media IDs, price, and sequence provenance. There can be only one
   outbox row per inbound row.
10. Commit the outbox status as `sending`, then call the provider exactly once.
11. Atomically store the returned provider message ID, mark the outbox `sent`,
    mark the inbound `completed`, and insert the processed-message marker.
    A supported PPV also moves only its exact sequence step to `sent` in this
    transaction.

The first scan of a conversation with no local checkpoint processes only the
newest `unreadCount` fan messages. A first-seen chat with no unread messages
establishes a baseline and does not reply to historical content.

## Failure behavior

- A failure before the provider call returns the inbound row to `pending`, up
  to three processing attempts.
- A restart may safely requeue `processing` rows whose outbox is absent or
  still `pending`.
- Once an outbox reaches `sending`, it is never sent automatically again.
- A provider exception or restart during `sending` changes the outbox to
  `delivery_unknown` and the inbound to `failed`.
- `delivery_unknown` requires manual provider-history reconciliation. This is
  deliberate: the provider may have accepted the request before the client
  timed out, so retrying could send a duplicate.
- A typed PPV intent on a provider without documented paid-message support is
  stored as `blocked_unsupported`; no provider request is made.

## Provider contract

The integration uses OnlyFansAPI's Fansly endpoints:

- `GET /api/fansly/{fanslyAccount}/chats` with `limit`, `offset`, and `order`;
- `GET /api/fansly/{fanslyAccount}/chats/{chat_id}/messages`;
- `POST /api/fansly/{fanslyAccount}/chats/{chat_id}/messages`.

The Fansly product is currently documented as closed beta. Endpoint changes
must be verified against the current OnlyFansAPI documentation before a
production release.

## Verification

The focused tests are:

```powershell
python -m pytest -q tests/persistence/test_pipeline.py
python -m pytest -q tests/persistence/test_message_pipeline.py
python -m pytest -q tests/messaging/test_policy.py
python -m pytest -q tests/persistence/test_purchases.py
```

The full test suite must also pass before publishing or deploying.
