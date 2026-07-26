# Purchase and PPV correctness

Phase 6 separates intent, delivery, revenue, and purchase attribution.

## State transitions

```text
typed PPV intent
  -> blocked_unsupported (provider lacks paid-message capability)

typed PPV intent
  -> sending
  -> sent + provider_message_id + exact sequence step SENT
  -> attributed purchase event
  -> exact sequence step BOUGHT/PENDING-next + fan totals advanced once
```

APIFansly enters the second path and sends the documented `access_type=["ppv"]`
payload with provider media, optional preview media, and a dollar price.

## Rules

- A free media message is not a PPV.
- A text offer is not treated as a sent PPV.
- A sequence is marked sent only when the provider returns a message ID.
- A wallet transaction is revenue evidence, not buyer identity.
- A fan purchase requires the exact fan ID, sent provider message ID, amount,
  and a unique provider purchase ID.
- Duplicate purchase events have no additional effect.
- A purchase advances only the sequence and step recorded on its outbox row.
- The recorded amount must equal the PPV price.
- Aftercare and fan spend must never use an aggregate wallet row.

## Automatic purchase attribution

APIFansly's `ppv.purchased` webhook binds a unique order ID to the purchased
account-media ID, fan ID, creator ID, and price. The adapter stores the
`contentId` returned by the PPV send as the outbox purchase reference. Webhook
ingestion then resolves the exact sent PPV and calls the same idempotent
purchase transition used by the durable sequence engine.

There is no human handoff or amount/time-window guessing in this path. Unknown
media references, wrong fans, wrong creators, wrong amounts, duplicate order
conflicts, and purchases that do not match a sent PPV fail closed.

OnlyFansAPI remains a free-message fallback and produces
`blocked_unsupported` for PPV intents.

## Verification

```powershell
python -m pytest -q tests/test_apifansly_client.py
python -m pytest -q tests/messaging/test_models.py
python -m pytest -q tests/persistence/test_purchases.py
python -m pytest -q tests/persistence/test_message_pipeline.py
python -m pytest -q tests/persistence/test_migrations.py
```
