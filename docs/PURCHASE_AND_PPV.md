# Purchase and PPV correctness

Phase 6 separates intent, delivery, revenue, and purchase attribution.

## State transitions

```text
typed PPV intent
  -> blocked_unsupported (current Fansly provider contract)

typed PPV intent
  -> sending
  -> sent + provider_message_id + exact sequence step SENT
  -> attributed purchase event
  -> exact sequence step BOUGHT/PENDING-next + fan totals advanced once
```

The second path is implemented for a future provider capability but cannot be
entered by the current OnlyFansAPI Fansly client because paid-message fields
are not documented.

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

## Current provider limitations

OnlyFansAPI documents free text/media sending for Fansly but currently does not
document a price or paywall field. Its Fansly wallet ledger exposes transaction
amounts and timestamps but not fan or message attribution.

The safe behavior is therefore:

- preserve a generated PPV decision for operators as
  `blocked_unsupported`;
- never send undocumented `requirePurchase`, `price`, `previews`, or access
  fields;
- ingest wallet rows idempotently for aggregate reporting;
- leave per-fan purchase counts unchanged until an attributable event exists.

## Verification

```powershell
python -m pytest -q tests/test_fansly_api_client.py
python -m pytest -q tests/messaging/test_models.py
python -m pytest -q tests/persistence/test_purchases.py
python -m pytest -q tests/persistence/test_message_pipeline.py
python -m pytest -q tests/persistence/test_migrations.py
```
