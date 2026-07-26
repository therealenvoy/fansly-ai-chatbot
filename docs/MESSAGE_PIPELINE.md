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
11. Atomically store the returned provider message ID and PPV account-media
    purchase reference, mark the outbox `sent`, mark the inbound `completed`,
    and insert the processed-message marker.
    A supported PPV also moves only its exact sequence step to `sent` in this
    transaction.
12. On `ppv.purchased`, authenticate the webhook route, match the event's
    account-media ID to that stored reference, verify fan/creator/amount, and
    advance the exact sequence step idempotently.

The first scan of a conversation with no local checkpoint processes only the
newest `unreadCount` fan messages. A first-seen chat with no unread messages
establishes a baseline and does not reply to historical content.

## CRM history synchronization

The CRM history mirror is intentionally separate from the automated
inbox/outbox above. Pausing automated replies does not pause CRM visibility.

1. Every cycle checks the newest provider chat page. During initial discovery,
   it also advances a durable cursor through older chat pages.
2. Every discovered chat creates or updates its fan identity, username, avatar,
   provider head message ID, and independent CRM synchronization state.
3. Recent changed chats are synchronized before deep history. Both fan and
   creator messages are stored with provider IDs, provider timestamps, chat
   IDs, and attachment metadata.
4. Older message cursors are persisted after every page. A restart resumes the
   exact backfill instead of starting over.
5. Provider message IDs make repeated pages idempotent. CRM synchronization
   never inserts into `inbound_messages`, so imported history cannot trigger
   automated replies when the bot is later enabled.
6. The dashboard reads actual `fan_messages` counts and exposes history in
   100-message pages. “Load older messages” can traverse the entire stored
   conversation while the list shows whether provider history is still
   syncing.

`CRM_SYNC_MESSAGE_PAGES_PER_CYCLE` and
`CRM_SYNC_DISCOVERY_PAGES_PER_CYCLE` bound provider usage. OnlyFansAPI charges
per request, so the initial full-history import is deliberately resumable
instead of one unbounded burst.

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

Production paid PPV uses APIFansly:

- `GET /{account_id}/chats` with cursor pagination and sort order;
- `GET /{account_id}/chats/{chat_id}/messages`;
- `POST /{account_id}/chats/{chat_id}/messages`;
- vault album and album-media reads for exact media selection.

The durable pipeline is provider-neutral. Only the adapter owns authentication,
pagination, response normalization, and paid-message payload fields.

## Verification

The focused tests are:

```powershell
python -m pytest -q tests/persistence/test_pipeline.py
python -m pytest -q tests/persistence/test_message_pipeline.py
python -m pytest -q tests/messaging/test_policy.py
python -m pytest -q tests/persistence/test_purchases.py
```

The full test suite must also pass before publishing or deploying.
