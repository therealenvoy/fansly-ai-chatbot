# Truthful Dashboard Contract

The dashboard reports only durable facts that the application can prove. A
missing provider capability is shown as unavailable or blocked, not converted
into a synthetic success, zero, or estimate.

## Canonical data sources

| Dashboard value | Canonical source |
| --- | --- |
| Known fans | Durable `fans` rows plus persisted fan notes |
| Completed inbound messages | `inbound_messages` with `status = completed` |
| Sent messages by kind | `outbox_messages` with `status = sent` |
| Blocked PPV intents | `outbox_messages` with `status = blocked_unsupported` |
| Delivery-unknown messages | `outbox_messages` with `status = delivery_unknown` |
| Attributed purchases and revenue | Exact, idempotent `purchase_events` |
| Aggregate provider balance | Latest durable `provider_wallet_transactions` row |
| Conversation state | Durable fan, runtime-state, conversation, and message rows |

Legacy purchase totals stored in fan-note JSON are not used for revenue,
purchase counts, average order value, or fan spend. Provider wallet
transactions are aggregate account records and are never assigned to a fan
without an exact attributed purchase event.

## Explicitly unavailable metrics

The current provider contract does not provide enough evidence for:

- subscription revenue by fan;
- a chatting-to-subscriber ratio;
- durable script completion rate;
- the old revenue-dependent health label.

These values are returned as `null` with a reason in `unavailable_metrics`.
They are displayed as `N/A`, never as fabricated zeroes.

## Provider and bot status

- `startup_verified` means authentication passed during application startup.
- `live_verified` is returned only after the operator runs the live connection
  test and the provider accepts it.
- `offline` includes the current bounded error detail.
- Bot status distinguishes runtime availability, runtime enabled state, the
  persisted enabled state, and whether those states agree.
- A bot toggle persists the requested state before changing runtime state. If
  runtime application fails, the persisted setting and runtime state are
  rolled back.

## Content and PPV controls

Local files under the dashboard vault path are inventory only. They are not
provider-ready media. A sendable media reference must be a provider-issued ID.

APIFansly advertises paid messages and vault albums, so PPV sequences can be
activated with that provider. The dashboard browses the connected Fansly vault,
shows available image/video previews, and saves the selected media and optional
preview IDs. Sequence and step changes remain atomic.

Provider vault browsing and PPV activation remain blocked unless the selected
client explicitly advertises those capabilities.

The operator media registry remains separate from the native Fansly vault. It
adds searchable labels and tags to provider IDs; it is not presented as a full
vault sync.

## Configuration controls

Creator persona YAML is validated before an atomic file replacement. When the
running bot uses that creator, the validated persona is reloaded immediately;
the response reports whether the runtime update succeeded.

The normal dashboard presents the persona as structured fields. The server
still validates the complete `PersonaDocument`, preserves fields not changed
by the form, and writes the same durable creator configuration.

Creator script changes are stored as durable overrides. Built-in scripts remain
the fallback; an active override with the same name replaces the built-in at
runtime, and deleting the override restores the built-in.

The brand-bible file is an operator reference only. Saving it is atomic, but
the bot does not consume it at runtime and the dashboard says so explicitly.
