# Continuous Integration

GitHub Actions runs three independent checks from
`.github/workflows/ci.yml`.

## Core

The core job installs exactly the production dependency set plus pytest,
compiles the source tree, and runs every test except the optional emotion suite
and the PostgreSQL-only test. This is the fast required gate for ordinary bot,
dashboard, provider, and persistence changes.

## PostgreSQL integration

The PostgreSQL job starts a clean PostgreSQL 16 service, applies every Alembic
migration, initializes the application-owned compatibility tables, and verifies
the durable inbox/outbox workflow:

- duplicate provider messages are idempotent;
- the oldest inbound message is claimed first;
- an approved response is placed in the outbox;
- delivery records the provider message ID;
- the inbound message becomes durably completed.

Local execution requires an isolated disposable database:

```text
TEST_POSTGRES_URL=postgresql://... python -m pytest -q tests/integration/test_postgres_runtime.py
```

Never point this test at production.

## Optional emotion system

The emotion job installs `requirements-dev.txt` and runs the legacy
FastAPI/VADER/BERT tests separately. Keeping it separate prevents the production
image and fast core job from downloading Torch.

## Merge and deployment gate

Before treating a commit as releasable, require all three GitHub checks to pass.
Railway deployment should target only a commit that has passed those checks;
the workflow does not deploy or mutate Railway by itself.
