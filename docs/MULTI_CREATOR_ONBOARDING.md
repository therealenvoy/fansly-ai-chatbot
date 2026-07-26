# Multi-creator onboarding boundary

The runtime is ready for instant-first inbox loading per creator, but the
current deployment still starts one configured creator worker. A dashboard
form for storing multiple provider credentials does not exist yet and should
not be faked by putting secrets in browser storage.

## Required connection lifecycle

Each onboarded model must have an independent lifecycle:

1. Create a stable internal `creator_id`.
2. Store the provider credential in a secret manager, referenced by creator;
   never store or return the raw credential through the CRM API.
3. Start one provider adapter and one `CrmSyncService` for that creator.
4. Verify provider authentication.
5. Prime the newest chat-index page. The model's inbox is now usable.
6. When an operator opens a chat, hydrate only that chat's newest message page.
7. Continue older chat discovery and full message history in bounded,
   resumable background pages.
8. Keep automated replies disabled until that creator independently passes
   launch guards and is explicitly enabled.

## Isolation rules

- Every fan, conversation, message, sync cursor, purchase, inbound, and outbox
  query must include `creator_id`.
- A request must resolve its creator from authenticated server-side context,
  not from an arbitrary browser-supplied ID.
- Provider clients and synchronization locks are per creator. A slow backfill
  for one model must not block another model's inbox.
- One creator's provider error must degrade only that creator to its durable
  cache.
- Enabling the bot is a separate, creator-scoped action. Connecting a model or
  viewing chats must never enable replies.

## Control plane still required

Before multi-model onboarding is production-ready, add:

- an encrypted creator-connection registry;
- authenticated creator/workspace membership and a server-side selector;
- a worker supervisor that starts, stops, and health-checks one runtime per
  connected creator;
- per-creator sync progress and provider-credit telemetry;
- credential rotation and disconnect workflows;
- end-to-end tests proving creator A cannot read or mutate creator B.

The current creator-keyed database and instant-first CRM service are the data
and runtime foundation for that control plane; they are not a claim that the
multi-model credential UI is already complete.
