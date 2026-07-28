# Human Delivery V1

## Deployment state

Human Delivery is an independent, fail-closed layer around the existing
conversation system. Deploying its schema and CRM does not replace the live
responder. The default state is:

- `HUMAN_DELIVERY_ENABLED=false`
- `HUMAN_DELIVERY_MODE=off`
- shadow, live, and maximum live percentages are zero
- multi-bubble sending is false
- prompt compiler, Memory V2 integration, typos, and advanced candidates are
  false

The current conversation-only responder remains the only live authority. It
continues to use the existing durable inbound/outbox path and one visible
message per inbound row. Human Delivery repositories do not import or write the
outbox table.

## Existing production path retained

The retained path is:

1. Signed `fansly.messages.received` webhook.
2. Universal webhook signature and account validation.
3. Idempotent provider-event ledger and durable inbound row.
4. Oldest-first worker claim.
5. Durable fan history, current persona, Brand Bible, chat guidance, and Brain
   context.
6. One DeepSeek conversation decision.
7. Existing policy, style, and quality gates.
8. One durable outbox row linked to the inbound row.
9. Contact permission recheck and provider delivery.
10. `fansly.messages.sent` reconciliation.

Provider reads are not part of this path. Webhooks are the real-time authority
and recovery reconciliation remains separately controlled.

The legacy CRM accepts 50,000 characters of chat instructions and 20,000
characters of Brand Bible. The old runtime slices each prompt document to
20,000 characters. This can hide instructions at the end of an accepted
document. Human Delivery keeps the originals unchanged and introduces a
section-based compiler that reports every budget omission.

## New data model

Migration `20260729_22` adds only new tables and nullable/defaulted columns:

- `conversation_documents` and `conversation_document_events`
- `conversation_examples`
- `fan_turns` and `fan_turn_inbound_links`
- `creator_facts`
- `fan_style_profiles`
- `human_response_plans` and `human_response_bubbles`
- `human_delivery_reviews`
- provenance and contradiction fields on Memory V2
- interpretable evidence, confidence, relationship, and style fields on the
  existing fan conversation state

The document bootstrap is idempotent. It snapshots the current Persona, Brand
Bible, and chat guidance once. It creates the cleaned Conversation Guide and an
inactive Sales/PPV placeholder as drafts. It never overwrites later operator
revisions.

## Prompt governance

The compiler uses complete heading/paragraph chunks under an explicit budget.
It reserves space for hard runtime rules and the newest fan turn before adding
optional material. Relevant chunks are ranked deterministically against the
current synthetic or future shadow context. The privacy-safe report contains
labels, sizes, omission reasons, and a prompt fingerprint, not prompt text.

Conversation-only compilation always excludes the Sales/PPV Playbook. New CRM
document activation changes only the inert versioned store while the deployment
flags are off. It does not rewrite legacy settings or current live prompts.

The linter reports, without mutating content:

- legacy runtime overflow and overlong sections
- sales rules mixed into conversation documents
- fabricated scarcity, guilt, pressure, or dependency rules
- rigid question and phrase quotas
- duplicate instructions
- conflicting pet-name or emotional-positioning rules
- conflicting stable creator facts
- missing factual-grounding rules

## Turns, plans, and cancellation

When observation is explicitly enabled in a future shadow rollout, a fan turn
groups already-persisted webhook messages for one fan/chat. Defaults are a
four-second quiet window and a twelve-second maximum window. Membership is
unique, restart-safe, duplicate-safe, and re-ordered by provider timestamp.
Older webhook events arriving later converge into the same open turn.

A structured Human Delivery decision permits one to three meaningful bubbles,
one question total, no private reasoning fields, and no sales, PPV, media, tip,
or unsupported creator claims. Invalid output returns a fallback state and does
not persist a plan.

Shadow plans and bubbles have stable fingerprints, order, idempotency keys, and
durable `available_at` values. New fan messages, creator/native sends, message
deletion, bot disablement, and provider authentication failure cancel open
Human Delivery work. This cancellation does not modify the live outbox.

Model-powered shadow is deliberately not wired to the production worker. It
would add a second model call per sampled turn. A one-call planner is available
for a separately authorized shadow worker, but all shadow flags deploy at zero.

## Voice Lab

The authenticated CRM Voice Lab provides:

- document revision selection, lint findings, character counts, and draft
  activation inside the inert review store
- a deterministic synthetic preview with casing, question, repetition, lint,
  and prompt-budget reports
- zero provider calls and zero outbox writes in preview
- tagged winning-example drafts
- a verified creator-fact ledger
- an evidence-backed fan-memory viewer with correction API and soft
  deactivation
- aggregate shadow plan and bubble status
- normalized feature flags and explicit safety boundaries

Synthetic preview data must not contain real fan data. The fan-memory viewer is
an authenticated operator tool and must never be copied into aggregate logs.

## Style and quality controls

The style fingerprint uses at most 50 stored samples. It measures lowercase
ratio, message length, emoji frequency, question frequency, punctuation
density, and common abbreviation use. These are soft signals.

Mostly-lowercase mode protects URLs, codes, and uppercase identifiers and is
disabled for serious content. Typos are off by default. If separately enabled,
at most one low-risk, deterministic internal letter swap is possible; retries
produce the same result and serious text is never modified.

Semantic repetition uses bounded token and bigram signatures over recent
creator text. Question fatigue blocks a new planned question after two
consecutive creator question turns. These checks use no local model, GPU,
embedding service, or provider read.

## Verification and promotion

The synthetic evaluation contract is
`tests/fixtures/human_delivery_eval_v1.json`. It covers multi-message turns,
question fatigue, emotional and boundary cases, callbacks, fact conflicts,
language variation, manual interruption, deletion, duplication, and
out-of-order delivery. It contains invented content only.

Deployment is not activation. Separate operator authorization is required for
each of:

1. activating a cleaned prompt revision in the live compiler
2. enabling model-powered shadow sampling
3. selecting a controlled canary audience
4. granting one-bubble Human Delivery live authority
5. enabling durable multi-bubble outbox integration
6. raising any live rollout percentage

Live promotion must retain conversation-only policy, one-model-call normal
turns, deployment percentage ceilings, provider contact permission checks,
delivery-unknown protection, and the existing outbox as the only send boundary.
