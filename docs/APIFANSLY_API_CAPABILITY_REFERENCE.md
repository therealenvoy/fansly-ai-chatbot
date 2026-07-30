# APIFansly API Capability Reference

> Canonical project reference for APIFansly feature work.
>
> Audit date: 2026-07-30
> Official documentation reviewed: 61 unique pages from the 63 URLs supplied by the operator
> Duplicates removed: `posts/post-settings/pin-post` and `media/media-permissions`
> API calls made during this audit: none; only public documentation pages were read
> Provider base URL: `https://v1.apifansly.com/api/fansly`

## Mandatory use

Before changing any APIFansly-backed feature:

1. Read the relevant section of this document.
2. Re-open the linked official page because APIFansly is an external, changing contract.
3. Compare the current page with the method, route, units, identifiers, and payload recorded here.
4. Inspect the existing adapter before adding a parallel client.
5. Add a sanitized contract fixture and a focused test before making a production request.
6. Keep API keys, account credentials, 2FA codes/tokens, fan identifiers, messages, and signed CDN URLs out of logs and fixtures.

This is a contract map, not permission to activate sending, posting, account mutation, PPV, or outreach.

## Global contract

### Authentication

Every API request uses the `x-api-key` header. The key belongs on the server only; never return it to the browser or place it in client-side JavaScript.

### Response envelope

The documented outer envelope is:

```json
{
  "statusCode": 200,
  "message": "Success",
  "data": {},
  "timestamp": "2026-01-09T21:59:45.908Z"
}
```

Many Fansly account endpoints add nested layers:

```text
data.status_code
data.data.success
data.data.response
```

Not every endpoint uses the same nesting. Media upload, account connection, and some newer endpoints differ. Parse defensively, but reject malformed success responses instead of silently returning empty data.

### Rate and credit rules

- Standard request: 1 credit for up to 80 KB; larger responses consume credits proportionally in 80 KB units.
- Media upload/download: 2 credits per MB.
- Webhooks: 80 delivered events per credit.
- Published rate limits: Starter 600 RPM, Pro 1,000 RPM, Enterprise custom/unlimited.
- A `429` response requires bounded exponential backoff and respect for `X-RateLimit-Retry-After`.
- Useful headers include `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Plan`, and `X-RateLimit-Retry-After`.
- Cache stable reads, use cursors, batch where possible, and do not poll a full account repeatedly.

The public documentation review used zero APIFansly API credits.

### Identifier dictionary

| Name | Meaning |
|---|---|
| Connected `account_id` / `accountId` | APIFansly's internal connected-account ID, commonly shaped like `fansly_...`; used in most account-scoped routes. |
| Native Fansly account ID | Fansly's platform user/account ID returned inside account/profile payloads. It is not interchangeable with the connected-account ID. |
| `ids` on `/accounts/by-ids` | Comma-separated **native Fansly platform account IDs**, explicitly not APIFansly connected-account IDs. |
| `chat_id` / `chatid` | The chat `groupId` returned by List Chats. |
| `fan_id`, `target_user_id` | Native Fansly user/account ID for the fan. |
| `message_id` | Fansly message ID. |
| `mediaId` | Backend media object ID used by message/media permission payloads. |
| account-media ID | Account-owned media record returned by upload; some Fansly post payloads/responses distinguish it from `mediaId`. Confirm the current create-post contract before use. |
| `wallId` | Fansly wall identifier returned by Get Post Walls. |
| `post_id` | Fansly post or scheduled-post ID. |
| `scheduled_message_id` | Scheduled mass-message ID. |
| `automated_message_id` | Automated-message rule ID; required by the documented delete URL even though the path-parameter table omits it. |

The documentation inconsistently spells path placeholders (`account_id`/`accountId`, `chat_id`/`chatid`). Match the route, not the placeholder style.

### Unit dictionary

Do not create one global “money” or “timestamp” conversion:

| Context | Documented unit |
|---|---|
| Message/post/mass-message PPV `price` | Dollars; PPV is documented as $1–$500. |
| Subscriber `price` / `renewPrice` | Cents. |
| Earnings summary values | Base units divided by 1,000 to obtain dollars. |
| Post `scheduledFor` / `expiresAt` | Unix milliseconds. The live Create Post page explicitly documents milliseconds and provides a 13-digit example. |
| Analytics `afterDate` / `beforeDate` / `period` | Unix milliseconds. |
| Mass-message `scheduledFor` | Unix milliseconds. |
| Other response timestamps | Endpoint-specific; examples are not fully consistent, so normalize only after contract tests. |

Internally store currency as an integer plus an explicit scale/currency. Convert only at the provider boundary.

## Project implementation status

Status meanings:

- **Implemented**: a current adapter method covers the documented core contract.
- **Partial**: some behavior exists, but the complete contract is not implemented or a mismatch must be corrected.
- **Missing**: no production APIFansly adapter method was found.
- **Guide**: documentation shared by multiple endpoints, not a callable route.

Current source of truth: `src/apifansly_client.py`, with consumers in `src/bulk_posting`, `src/fyp_analytics`, and `src/creators/connections.py`.

## Chats

| Capability | Method and route | Important inputs and result | Project |
|---|---|---|---|
| [List Chats](https://docs.apifansly.com/api-reference/chats/list-chats) | `GET /{account_id}/chats` | Cursor pagination. `filter`: `all`, `vips`, `followers`, `subscribers`; optional `subscriptionTierId`, `search`; `sort`: `newest`, `oldest`, `unread`. Returns chats plus aggregated accounts; use `groupId` as `chat_id`. | **Partial** — list/cursor/sort exist, but `filter`, tier, search, and an explicit limit are not exposed correctly. |
| [Get Unread Chats](https://docs.apifansly.com/api-reference/chats/get-unread-chats) | `GET /{account_id}/chats/unread` | `cursor` is the last response item's `messageId`. Dedicated unread feed. | **Missing** |
| [Get Fan Chat Tips](https://docs.apifansly.com/api-reference/chats/get-fan-chat-tips) | `GET /{account_id}/chats/{fan_id}/tips` | Fan native user ID. Returns chat-tip history/summary. | **Missing** |
| [Get Chat Media Stats](https://docs.apifansly.com/api-reference/chats/get-chat-media-stats) | `GET /{accountId}/chats/{chatid}/media-stats` | Optional `cursor`; returns media performance within a chat. | **Missing** |
| [Mute Chat Notifications](https://docs.apifansly.com/api-reference/chats/mute-chat-notifications) | `POST /{account_id}/chats/mute` | JSON: `targetUserId`. | **Missing** |
| [Unmute Chat Notifications](https://docs.apifansly.com/api-reference/chats/unmute-chat-notifications) | `POST /{account_id}/chats/unmute` | JSON: `targetUserId`. | **Missing** |
| [Hide Chat](https://docs.apifansly.com/api-reference/chats/hide-chat) | `POST /{account_id}/chats/{chat_id}/hide` | No body documented. Hides a conversation from the inbox. | **Missing** |

## Chat messages

| Capability | Method and route | Important inputs and result | Project |
|---|---|---|---|
| [List Chat Messages](https://docs.apifansly.com/api-reference/chat-messages/list-chat-messages) | `GET /{account_id}/chats/{chat_id}/messages` | Optional older-message `cursor`; `limit` 1–10. Returns messages, delivery/read interactions, account media, and next cursor. | **Implemented** |
| [Create Group Chat](https://docs.apifansly.com/api-reference/chat-messages/create-group-chat) | `POST /{account_id}/group` | `users` must include creator and target user, both with `permissionFlags: 0`; `type` defaults to `1`; optional `recipients`, `lastMessage`, `userSettings`. | **Missing** |
| [Send Message](https://docs.apifansly.com/api-reference/chat-messages/send-message) | `POST /{account_id}/chats/{chat_id}/messages` | Required `content`; optional `mediaIds` and media permissions. Returns message ID and attachment metadata. | **Partial** — text, free media, and simple PPV exist; advanced permission combinations do not. |
| [Start Typing Indicator](https://docs.apifansly.com/api-reference/chat-messages/start-typing-indicator) | `POST /{account_id}/chats/typing` | JSON: `chatId`. Indicator lasts about five seconds; repeated calls must be bounded. | **Missing** |
| [Add Fan to VIP](https://docs.apifansly.com/api-reference/chat-messages/add-fan-to-vip) | `POST /{account_id}/chats/{fan_id}/vip` | Fan native user ID; no body documented. | **Missing** |
| [Read Receipts](https://docs.apifansly.com/api-reference/chat-messages/readreceipts) | `POST /{account_id}/chats/{chat_id}/readreceipts` | JSON `action`: `enable` or `disable`. | **Missing** |
| [Delete Message](https://docs.apifansly.com/api-reference/chat-messages/delete-message) | `DELETE /{account_id}/messages/{message_id}` | No body documented. Must tombstone locally and cancel conflicting pending work. | **Missing** |

The official Send Message code sample historically contained malformed illustrative JSON around `mediaIds`. Use the parameter table and Media Permissions guide, not a literal copy of that sample.

## Mass messaging and native automated messages

| Capability | Method and route | Important inputs and result | Project |
|---|---|---|---|
| [Get Mass Messages](https://docs.apifansly.com/api-reference/mass-messaging/get-mass-messages) | `GET /{account_id}/mass-messaging/scheduled` | Returns `scheduledBroadcastMessages` and recipient `groups`. `messageTemplate` may be a JSON string that needs a second parse. | **Missing** |
| [Send Mass Message](https://docs.apifansly.com/api-reference/mass-messaging/send-mass-message) | `POST /{account_id}/mass-messaging` | `content`; optional `mediaIds`, `scheduledFor`, permissions, and audience fields listed below. Immediate send when schedule omitted. | **Missing** — the local mass engine is not this provider contract. |
| [Update Mass Message](https://docs.apifansly.com/api-reference/mass-messaging/update-mass-message) | `PUT /{account_id}/mass-messaging/scheduled/{scheduled_message_id}` | `content`, required `scheduledFor`, optional media/permissions. | **Missing** |
| [Sent Mass Message Stats](https://docs.apifansly.com/api-reference/mass-messaging/sent-mass-messages-stats) | `GET /{account_id}/mass-messaging/stats/sent` | Cursor pagination; `limit` defaults to 24. | **Missing** |
| [Deleted Mass Message Stats](https://docs.apifansly.com/api-reference/mass-messaging/deleted-mass-messages-stats) | `GET /{account_id}/mass-messaging/stats/deleted` | Cursor pagination; `limit` defaults to 24. | **Missing** |
| [Get Automated Messages](https://docs.apifansly.com/api-reference/mass-messaging/get-automated-messages) | `GET /{account_id}/automated-messages` | Returns native automated-message rules, triggers, and templates. | **Missing** |
| [Create Automated Message](https://docs.apifansly.com/api-reference/mass-messaging/create-automated-message) | `POST /{account_id}/automated-messages` | Required `triggerType`, `content`; optional `delay`, `cooldown`, `subscriptionStreak`, `tipAmount`, `keywords`, media and permissions. | **Missing** |
| [Delete Automated Message](https://docs.apifansly.com/api-reference/mass-messaging/delete-automated-message) | `DELETE /{account_id}/automated-messages/{automated_message_id}` | The code examples include `automated_message_id`, although the page's path-parameter table lists only `account_id`. | **Missing** |

Mass-message audience fields:

- `includeFollowers`
- `includeSubscribersAutoRenewOn`
- `includeSubscribersAutoRenewOff`
- `includeExpiredSubscribers`
- `excludeCreators`
- `excludeOfflineUsers`
- `includeSubscriptionTierId`
- `includeListIds`
- `excludeListIds`
- `excludeUserIds`

All booleans default to false according to the documentation. Build an explicit audience preview and recipient estimate before a real send. Never infer “all fans” from omitted flags.

Native automated-message trigger types:

- `new_follower`
- `new_subscriber`
- `new_gift_link_subscriber`
- `subscriber_renew`
- `new_gift_link_subscriber_renew`
- `new_tip`
- `disabled`

`delay` and `cooldown` are seconds. `subscriptionStreak` applies to renewal triggers; `tipAmount` and `keywords` apply to tip triggers.

The supplied pages do **not** expose a fan-online-presence feed or an “online now” trigger. `excludeOfflineUsers` only filters a mass-message audience at send time. Do not design six-hour online outreach from these endpoints without another verified event/data source.

## Likes

| Capability | Method and route | Important inputs and result | Project |
|---|---|---|---|
| [Like Message](https://docs.apifansly.com/api-reference/likes/like-message) | `POST /{accountId}/messages/like` | JSON: `messageId`, `type` (example uses `1`). | **Partial / incorrect route** — current code calls `/{account}/chats/{chat}/messages/{message}/like`; fix before use. |
| [Unlike Message](https://docs.apifansly.com/api-reference/likes/unlike-message) | `POST /{accountId}/messages/unlike` | JSON: `messageId`, `type`. | **Missing** |

## Posts

| Capability | Method and route | Important inputs and result | Project |
|---|---|---|---|
| [List Posts](https://docs.apifansly.com/api-reference/posts/list-posts) | `GET /{account_id}/posts` | Returns account posts and associated media/account aggregation. No query parameters are documented on the supplied page. | **Missing** |
| [Create Post](https://docs.apifansly.com/api-reference/posts/create-post) | `POST /{account_id}/posts` | At least one of `content` or `mediaIds`; optional `postToFYP`, millisecond schedule/expiry, walls, pinning, reply/quote, and reply-permission fields. | **Implemented for content, media IDs, walls, schedule, and expiry** |
| [Delete Post](https://docs.apifansly.com/api-reference/posts/delete-post) | `DELETE /{account_id}/posts/{post_id}` | No body documented. | **Missing** |
| [Update Post](https://docs.apifansly.com/api-reference/posts/update-post) | `POST /{account_id}/posts/{post_id}` | Same body as create. Omitted fields are cleared by Fansly, so use read-modify-write. | **Missing** |
| [Get Wall](https://docs.apifansly.com/api-reference/posts/get-wall) | `GET /{accountId}/posts/wall/{wallId}` | Returns one wall and its post context. | **Missing** |
| [Get Post Walls](https://docs.apifansly.com/api-reference/posts/get-posts-walls) | `GET /{accountId}/posts/walls` | Returns wall IDs/names for the account. | **Implemented** |
| [Get Post](https://docs.apifansly.com/api-reference/posts/get-post) | `GET /{account_id}/posts/{post_id}` | Returns post, attachments, counts, media bundles/media, and account aggregation. | **Missing** |
| [Get Scheduled Posts](https://docs.apifansly.com/api-reference/posts/get-scheduled-posts) | Previously documented as `GET /{account_id}/posts/scheduled`; the supplied URL is no longer present in the live Posts navigation and currently cannot be treated as an authoritative contract. | **Blocked pending a current provider contract** |
| [Cancel Scheduled Post](https://docs.apifansly.com/api-reference/posts/cancel-scheduled-post) | `POST /{account_id}/posts/scheduled/{post_id}/cancel` | No body documented. | **Missing** |
| [Pin Post](https://docs.apifansly.com/api-reference/posts/post-settings/pin-post) | `POST /{account_id}/posts/{post_id}/pin` | JSON: `wallId`. | **Missing** |

Current live Create Post rules, re-verified from the rendered page HTML on 2026-07-30:

- At least one of `content` or `mediaIds` is required.
- `mediaIds` contains media IDs returned by Vault Media or Upload Media; the simple documented form is a string array.
- `postToFYP` is optional and requires a public video of at least three seconds.
- `scheduledFor` and `expiresAt` are Unix timestamps in milliseconds.
- `wallIds` is optional; omitting it posts to the default wall.
- The success response contains generated `attachments`, but `attachments` is not the current create request field.
- Update behavior must be separately verified before assuming omitted current content/media are preserved.

Documentation-drift warning: the page has changed between `mediaIds`/millisecond scheduling and `attachments`/unspecified timestamps. Re-open the live page and inspect its rendered request-body section before every posting-adapter change. Keep a sanitized fixture and focused request-shape test.

## Profile analytics

| Capability | Method and route | Important inputs and result | Project |
|---|---|---|---|
| [Profile Statistics](https://docs.apifansly.com/api-reference/profile-stats) | `GET /{accountId}/analytics/profilestats` | Optional millisecond `afterDate`, `beforeDate`, `period`; or `year`, `month`. Returns datapoints, traffic sources, top FYP tags/media, and media aggregation. | **Implemented** and consumed by FYP Analytics with a 30-minute creator/range cache, durable aggregate fallback, and a one-minute forced-refresh cooldown. |

Useful period values are `3,600,000` for one hour and `86,400,000` for one day. The response exposes media/profile time series, traffic sources, `topMediaOffers`, `topFypMediaOffers`, `topFypTags`, and aggregated account media. Keep signed media URLs short-lived and out of logs.

## Subscribers

All three subscriber list pages use the same route and differ by the `status` query.

| Capability | Method and route | Important inputs and result | Project |
|---|---|---|---|
| [All Subscribers](https://docs.apifansly.com/api-reference/subscribers/list-all-subscribers) | `GET /{accountId}/subscribers?status=all` | Optional `cursor`, `limit`, `subscriptionTierIds`, `search`. Returns stats, subscriptions, next cursor. | **Missing** |
| [Active Subscribers](https://docs.apifansly.com/api-reference/subscribers/list-active-subscribers) | `GET /{accountId}/subscribers?status=active` | Same pagination/filter fields. Active response examples use status `3`. | **Missing** |
| [Expired Subscribers](https://docs.apifansly.com/api-reference/subscribers/list-expired-subscribers) | `GET /{accountId}/subscribers?status=expired` | Same pagination/filter fields. | **Missing** |
| [Top Supporters](https://docs.apifansly.com/api-reference/subscribers/top-supporters) | `GET /{accountId}/top-supporters` | Optional millisecond `before`/`after`; returns ranked supporter data. | **Missing** |

Subscription responses include tier IDs/names, price and renewal price in cents, renewal/autorenew state, billing/duration, and millisecond lifecycle timestamps.

## Followers

| Capability | Method and route | Important inputs and result | Project |
|---|---|---|---|
| [Follow Account](https://docs.apifansly.com/api-reference/followers/follow-account) | `POST /{account_id}/follow/{target_user_id}` | Target is a native Fansly user ID. | **Missing** |
| [Unfollow Account](https://docs.apifansly.com/api-reference/followers/unfollow-account) | `POST /{account_id}/unfollow/{target_user_id}` | Target is a native Fansly user ID. | **Missing** |
| [Followers](https://docs.apifansly.com/api-reference/followers/followers) | `GET /{accountId}/followers` | Optional `cursor`, `limit`; returns relationship rows, aggregated accounts, next cursor. | **Missing** |
| [Following](https://docs.apifansly.com/api-reference/followers/following) | `GET /{accountId}/following` | Optional `cursor`, `limit`; returns followed accounts and next cursor. | **Missing** |

## Media and permissions

| Capability | Method and route | Important inputs and result | Project |
|---|---|---|---|
| [Upload Media](https://docs.apifansly.com/api-reference/media/upload-media) | `POST /{accountId}/media/upload`, then `GET /media/upload/{jobId}/status` | Multipart `file`; asynchronous job states `waiting`, `active`, `completed`, `failed`; completion returns `mediaId` and `accountMedia`. Signed CDN links expire after five hours. | **Implemented** |
| [Download Media](https://docs.apifansly.com/api-reference/media/download-media) | `POST /media/download` | JSON: `cdnUrl`; response is binary content. | **Missing** |
| [Media Permissions](https://docs.apifansly.com/api-reference/media/media-permissions) | Guide, not a route | Shared payload rules for DMs, posts, mass messages, and automated messages. | **Guide / partially implemented for DMs** |

`mediaIds` may contain a string media ID or an object:

```json
{
  "mediaId": "MEDIA_ID",
  "previewId": "OPTIONAL_PREVIEW_ID"
}
```

The array can mix strings and objects. With no access rules, attached media is free.

Simple root-level permission fields:

- `access_type`: one value or an array containing `ppv`, `subscription`, `follow`, `list`, `limited_time`
- `price`: dollars, required for PPV
- `subscriptionTierId`, `subscriptionTierName`, optional before/after fields
- `listId`, `listLabel` for list access
- `validBefore`, `validAfter` for limited-time access

Advanced `permissions` is an array of rules. Rules are **ORed**: any one matching rule unlocks the media. When `permissions` is supplied, root-level permission fields are ignored. Never combine the two forms and assume they are ANDed.

## Vault

| Capability | Method and route | Important inputs and result | Project |
|---|---|---|---|
| [List Vault Albums](https://docs.apifansly.com/api-reference/vault/list-vault-albums) | `GET /{accountId}/vault/albums` | Returns standard/custom albums, including common All/Posts/Messages albums. | **Implemented** |
| [Get Vault Album Media](https://docs.apifansly.com/api-reference/vault/get-vault-album-media) | `GET /{accountId}/vault/albums/{albumId}/media` | Optional cursor; returns vault media and next cursor. | **Implemented** |

For a media picker, store stable IDs and safe metadata. Do not persist temporary signed CDN URLs as durable identifiers.

## Earnings

| Capability | Method and route | Important inputs and result | Project |
|---|---|---|---|
| [Earning Statistics](https://docs.apifansly.com/api-reference/earnings/get-earning-statistics) | `GET /{account_id}/earnings` | Returns balance/summary data. Documented monetary values are base units divided by 1,000. | **Missing** |
| [Fan Earnings](https://docs.apifansly.com/api-reference/earnings/get-fan-earnings) | `GET /{account_id}/earnings/fans/{fan_id}` | Returns fan earnings over time, including gross/net totals. | **Missing** |
| [Fan Earnings by Source](https://docs.apifansly.com/api-reference/earnings/get-fan-earnings-by-source) | `GET /{account_id}/earnings/fans/{fan_id}/stats` | Returns fan earnings separated by monetary source. | **Missing** |
| [Monthly Earnings Statistics](https://docs.apifansly.com/api-reference/earnings/get-monthly-earnings-statistics) | `GET /{account_id}/earnings/monthly` | Examples use millisecond `after` and `before`; returns monthly gross/net totals and percentages. | **Missing** |

Never merge earnings base units with subscriber cents or PPV dollars before explicit normalization.

## Accounts and multi-model setup

| Capability | Method and route | Important inputs and result | Project |
|---|---|---|---|
| [List Accounts](https://docs.apifansly.com/api-reference/account/list-accounts) | `GET /accounts` | Returns all accounts managed by the API key. This is the correct discovery source for the model selector. | **Implemented** in the account connector and sync service. |
| [Get Accounts by IDs](https://docs.apifansly.com/api-reference/account/get-accounts-by-ids) | `GET /accounts/by-ids?ids=...` | `ids` are comma-separated native Fansly platform IDs, not connected-account IDs. | **Missing** |
| [Get Profile Data](https://docs.apifansly.com/api-reference/account/get-profile-data) | `GET /search/{username}` | Public/profile lookup by Fansly username. | **Missing** |
| [Get Current Account](https://docs.apifansly.com/api-reference/account/get-current-account) | `GET /{account_id}/me` | Returns the connected account's native Fansly profile/session-facing data. | **Implemented** |
| [Disconnect Account](https://docs.apifansly.com/api-reference/account/disconnect-account) | `DELETE /accounts/{accountId}` | Destructive provider mutation. Must also safely retire local creator-scoped runtime state. | **Missing** |

Model discovery calls `/accounts` only when the owner explicitly presses Sync, then upserts by the stable connected-account ID. Ordinary listing and selection use the local registry and consume no APIFansly credits. Never create a second local creator because a 2FA completion response was retried. Selecting a model is a local signed creator-scoped action; merely listing or selecting must not enable its chatbot.

## Connecting accounts and 2FA

| Capability | Method and route | Important inputs and result | Project |
|---|---|---|---|
| [Connect Account](https://docs.apifansly.com/api-reference/connect-fansly-account/connect-account) | `POST /connect` | `username`, `password`, dashboard `name`, uppercase ISO `countryCode`. Returns connected account or `requires_2fa`, temporary `twofa_token`, and masked delivery hint. | **Implemented** |
| [Submit Login 2FA](https://docs.apifansly.com/api-reference/connect-fansly-account/submit-2fa) | `POST /verify-2fa` | Resubmits `username`, `password`, `twoFactorToken`, `twoFactorCode`, `name`, `countryCode`. | **Implemented** |
| [Send Sensitive-Action OTP](https://docs.apifansly.com/api-reference/connect-fansly-account/send-otp) | `POST /{accountId}/twofa/session` | JSON: `useEmailTwoFAFallback`. This is a separate flow for sensitive actions, not the same as login `/verify-2fa`. | **Missing** |
| [Verify Sensitive-Action OTP](https://docs.apifansly.com/api-reference/connect-fansly-account/verify-otp) | `POST /{accountId}/twofa/session/verify` | JSON: `token`, `code`, `mode`. | **Missing** |

The provider's login 2FA wording refers to email in some responses, but the user may supply a valid authenticator/TOTP code. The application should label the field “verification code” and pass it through; it must not claim delivery by email unless the provider explicitly says so for that attempt.

Credentials may be held only for the short pending login challenge and must never be written to the database, response body, analytics, or logs. A completed provider account must be deduplicated by connected-account ID before local insert.

## Feature implementation playbooks

### Inbox and AI replies

1. Use signed webhooks as the real-time authority.
2. Use List Chats and List Chat Messages only for bounded backfill/reconciliation.
3. Persist cursors per creator/chat; never rescan every chat from zero.
4. Treat `groupId` as the chat ID and native fan account ID as the fan ID.
5. Reconcile sent messages from webhook/provider IDs before a new AI reply.
6. Use typing indicator only after a reply is accepted for delivery, with a strict call cap.
7. Use read/delete events and APIs to keep local context convergent.

### One-to-one free media or PPV

1. Select durable vault media or upload once.
2. Wait for upload job completion.
3. Use `mediaId`; add `previewId` when required.
4. Free media: omit permission fields and price.
5. PPV: `access_type: ["ppv"]`, price in dollars, $1–$500.
6. Send through the durable outbox with idempotency and delivery reconciliation.
7. Attribute purchases from authenticated provider events, not optimistic send responses.

### Native automated messages

1. GET existing rules first.
2. Match ownership using a local provider-rule ID and creator ID.
3. Preview trigger, delay, cooldown, audience, media, and permissions.
4. POST only after explicit operator activation.
5. Store the returned rule identity.
6. DELETE only the exact application-owned rule ID.

This is cheaper and more reliable for the documented native triggers than simulating them with polling. The supplied native triggers do not include online presence.

### Mass messages

1. Build the target flags explicitly.
2. Show inclusion/exclusion configuration and an estimated audience.
3. Require preview/confirmation for immediate sends.
4. Prefer a future `scheduledFor` during initial rollout.
5. Persist the scheduled provider ID before reporting success.
6. Reconcile with scheduled/sent/deleted stats.
7. Never retry an ambiguous POST automatically without an idempotency/reconciliation strategy.

### Bulk/FYP posting

1. Upload media and poll one job with bounded backoff.
2. Validate public video and duration before `postToFYP`.
3. Resolve wall IDs from Get Post Walls.
4. Convert schedule/expiry to Unix milliseconds at the provider boundary.
5. Send the uploaded `mediaId` values in `mediaIds`; do not send response-only attachment objects as the create request.
6. Save the provider post ID.
7. Reconcile with Get Scheduled Posts/Get Post.
8. Update by fetching current content/media first because omitted fields are cleared.
9. Cancel through the provider endpoint and mark local state only after a confirmed response.

### FYP analytics

1. Query Profile Statistics with a bounded time range and suitable bucket.
2. Cache each creator/range for 30 minutes and enforce a one-minute
   forced-refresh cooldown.
3. Normalize top FYP tags/media from the response, not from fabricated scores.
4. Store aggregate measurements, not temporary signed media URLs.
5. Compare periods locally rather than repeatedly calling overlapping provider ranges.
6. Persist aggregate snapshots without temporary signed media URLs, and use
   stale data only as a visible fallback when the provider read fails.

### Audience and CRM

1. Backfill subscribers/followers with cursors.
2. Keep subscription status, tier, lifecycle times, and follower relation separate.
3. Normalize each monetary scale at ingestion.
4. Use webhooks for changes after backfill.
5. Derive supporter segments from stored normalized facts, not repeated per-fan reads.

### Multi-model management

1. Discover with an explicit owner-triggered `GET /accounts`; never call it
   during ordinary model listing or selection.
2. Upsert by connected-account ID.
3. Fetch `/me` only when profile data is absent/stale or activation requires identity verification.
4. Keep every cache, cursor, webhook, outbox row, automation, vault choice, post, and analytic range creator-scoped.
5. New models default to bot disabled.
6. Model selection changes dashboard context only; it does not activate chat/post automation.
7. Return the sanitized model registry with the selection response so the
   browser does not immediately repeat `GET /api/models`.

## Known documentation and implementation hazards

1. Placeholder spelling is inconsistent; do not create multiple concepts from `account_id` versus `accountId`.
2. Connected APIFansly account IDs and native Fansly IDs are different.
3. Chat IDs are group IDs.
4. The Delete Automated Message examples contain an ID path segment omitted from its parameter table.
5. The Send Message example has had malformed illustrative `mediaIds` JSON.
6. `permissions` rules are OR, and override root-level media permission fields.
7. Money uses dollars, cents, or 1/1000 base units depending on the endpoint.
8. The live Create Post contract has drifted between request shapes. As of the 2026-07-30 recheck, the request uses `mediaIds` and millisecond schedule/expiry values; the response contains generated `attachments`.
9. Media upload is asynchronous and CDN URLs expire after five hours.
10. Update Post clears omitted fields.
11. The current Like Message client route disagrees with the official route/body.
12. The supplied endpoint set has no online-presence event/feed.
13. A successful network response is not enough; require the documented inner success shape and provider resource ID.
14. Do not retry ambiguous mutations blindly.

## Definition of ready for a new APIFansly feature

- Relevant official page rechecked on the implementation date.
- Method, route, IDs, units, pagination, and response nesting captured in a focused test.
- Creator scoping enforced.
- No secrets or fan content logged.
- Read cost bounded and cached.
- Mutation is idempotent or explicitly reconciled.
- Preview cannot mutate.
- Provider failure and `402`/`429` behavior handled.
- No automatic activation from account connection or model selection.
- Exact production capability remains behind an explicit control until verified.

## Official foundations

- [API overview](https://docs.apifansly.com/api-reference)
- [Authentication](https://docs.apifansly.com/introduction/essentials/authentication)
- [Rate limits](https://docs.apifansly.com/introduction/essentials/rate-limits)
- [Credit system](https://docs.apifansly.com/introduction/essentials/credits)
- [Response structure](https://docs.apifansly.com/introduction/essentials/response-structure)
