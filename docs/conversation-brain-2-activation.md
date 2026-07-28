# Conversation Brain 2.0 production activation

## Authority design

Actual delivery still has one path: a validated ConversationDecision is persisted, then the durable idempotent outbox worker sends it. Neither ShadowBrainService nor AdvancedBrainDecisionService can call Fansly or write to the outbox.

- current: only the current conversation brain runs.
- shadow: current remains authoritative; Brain 2.0 runs asynchronously and stores a blinded comparison pair.
- advanced: sticky creator/fan/version assignment may select Brain 2.0, bounded by both runtime percentage and the deployment ceiling. Every advanced failure falls back to current.

The authority hierarchy is deployment guard, runtime mode, requested percentage, deployment ceiling, sticky assignment, structured contract, deterministic quality gate, existing conversation-only policy, style approval, then the single outbox.

## Provider contracts

All fast, planner, candidate and judge calls use stable JSON Output plus strict local Pydantic schemas. The implementation classifies empty, truncated, malformed, schema-invalid, timeout, rate-limit and server failures without logging prompts, responses, fan identifiers or credentials. One bounded retry or repair is allowed, and every request consumes the per-turn, hourly, daily and cost controls.

## Safe deployment variables

Pre-live production must keep:

- BRAIN_ALLOW_ADVANCED_SEND=false
- BRAIN_LIVE_PERCENT=0
- BRAIN_MAX_LIVE_PERCENT=0
- the existing bot enabled state unchanged

BRAIN_MAX_LIVE_PERCENT is deployment-only. Raising it requires a Railway variable change and successful deployment. Runtime mode and requested percentage are creator-scoped database settings and apply without restart.

## Rollback

POST /api/brain/rollback from the authenticated CRM sets mode to current and requested live percentage to zero in one audited action. It does not disable the entire bot. In-flight advanced results are rejected if the authority signature changed before return. Automatic rollback evaluates safety immediately and failure/JSON/timeout/latency thresholds over the last 100 advanced attempts.

## Promotion gate

The CRM refuses a non-zero requested live percentage until its durable pre-live gate is green: 200 uncapped attempts, 99% completion, classified failures, JSON/schema and provider transient rates under threshold, latency targets, 200 blinded reviews, 55% non-tied Brain 2.0 wins, and zero approved safety or shadow outbox violations. Promotion is never automatic.

## Verification

Before a canary, verify the exact Git commit in GitHub and Railway, terminal CI/deployment success, /ready, Alembic revision, required tables, bot state, current authority, deployment guard, requested percentage zero, aggregate shadow reliability, safety tests, blinded-review evidence, cost telemetry, fallback, rollback and zero shadow outbox writes. No real test message is needed or permitted during pre-live deployment.
