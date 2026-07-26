# Durable state

Production state is stored in PostgreSQL through one shared SQLAlchemy engine.
SQLite is supported only for local development and isolated tests; startup
fails closed if a Railway production environment is configured with SQLite.

## Schema ownership

Alembic owns the schema. Application startup runs:

```text
alembic upgrade head
```

programmatically before repositories or the dashboard begin serving.
Migration `20260726_01` is an immutable baseline and preserves values from the
legacy global `bot_settings` table. Migration `20260726_02` adds typed outbound
payloads, the provider wallet ledger, and attributed purchase events. Migration
`20260726_03` adopts the pre-existing fan-note, message-history, and PPV
sequence tables without deleting their data.

The durable model contains:

- creators and creator-scoped settings;
- fans, provider conversations and incremental poll cursors;
- funnel, rhythm, extraction, purchase and activity state;
- processed platform-message IDs with database uniqueness;
- inbound-message and outbox tables for the Phase 5 delivery pipeline.
- provider wallet transactions kept separate from attributed fan purchases;
- exact purchase-to-outbox provenance for PPV sequence progression.

`fan_notes`, `fan_messages`, and the PPV sequence tables now belong to the same
authoritative metadata and migration chain. Repository-level create helpers are
retained only for isolated tests; application startup never creates schema
outside Alembic.

## Local migration checks

```powershell
python -m alembic upgrade head
python -m alembic current
```

Set `DATABASE_URL` before running either command. Never point migration tests at
the production database.
