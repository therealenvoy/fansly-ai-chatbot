# Conversation Brain 2.0 design

## Safety boundary

The existing conversation brain remains the only live author of outbound text.
Brain 2.0 initially runs as an isolated shadow observer: it receives an immutable
context snapshot, stores structured results, and has no dependency on or access
to `MessageProcessingRepository.enqueue_outbox`. Shadow failures are logged and
must never fail or delay the live response path. Conversation-only policy, PPV
blocking, webhook ingestion, polling reconciliation, and the persisted bot
enabled state remain unchanged.

## Data model

Revision `20260728_10` is additive and creates:

- `conversation_outcomes`: one row per sent conversation decision, linked to
  inbound, outbox, creator, fan, brain/model version, trigger, experiment, and
  deterministic reply/continuation/return/recovery/negative outcomes.
- `fan_memories`: evidence-backed typed memories with source message,
  confidence, importance, expiry, and supersession.
- `conversation_episodes`: idempotent structured summaries retaining exact
  source message ranges.
- `fan_conversation_states`: one versioned row per creator/fan for relationship,
  mood, energy, engagement, objective/tactic/thread, and repetition counters.
- `brain_shadow_runs`: router, candidate, judge, gate, timing, and failure
  records. This table deliberately has no outbox foreign key.
- `brain_experiments`, `brain_experiment_variants`, and
  `brain_experiment_assignments`: durable audited experiments with sticky
  per-fan assignment and no automatic promotion.

Existing flat fan notes and conversation decisions remain readable. Backfill to
Memory V2 is explicit, idempotent, and never deletes or rewrites legacy notes.

## Live fast path

The current one-call brain is hardened in place:

1. Build context from persona, guidance, recent verbatim history, relevant
   active memories, recent episodes, durable state, and the previous decision.
2. Validate the strict decision schema.
3. Permit one configured JSON repair call for malformed/truncated output.
4. Apply deterministic conversation-only, factuality, repetition, question,
   pet-name, length, and prompt-injection gates.
5. Persist the approved decision, enqueue through the existing durable outbox,
   and create an outcome row only after delivery is provider-confirmed.
6. If generation fails, use a conservative trigger-aware fallback only when it
   passes every deterministic gate; otherwise retain the existing retry path.

The newest eligible sent creator message before a fan reply owns that reply.
Attribution uses stable message IDs and timestamps so one reply cannot be
claimed by multiple outcomes.

## Shadow strategic path

An auditable deterministic router selects fast or strategic analysis using
message length, vulnerability/boundary markers, stalled trigger, contradictory
memory, recent failed tactics, low context confidence, and engagement shifts.

Strategic shadow analysis uses bounded contracts:

1. Planner: structured evidence labels, state, objective, tactic, constraints.
2. Writer: warm, playful, and direct candidates.
3. Independent judge: blinded scorecard, hard failures, winner, confidence.
4. Deterministic gate: machine-readable hard-failure codes.

Creator hourly/daily caps, per-turn call caps, timeouts, and deterministic
sampling apply before calls. Shadow work executes after the live response is
prepared and never changes the live decision or outbox. Settings are persisted
per creator and read at runtime without a process restart.

## Memory and episodes

Memory extraction and episode summarization are best-effort post-processing.
Every memory has source evidence. Explicit contradictions supersede older
values while preserving audit history. Boundaries do not expire; temporary
facts lose retrieval priority or expire. Retrieval is deterministic by status,
type relevance, open-thread relationship, importance, confidence, and recency.

Recent messages remain verbatim. Older messages may be summarized into
idempotent episodes without deleting source messages.

## Evaluation and operations

`scripts/evaluate_brain.py` runs synthetic/anonymized fixtures against current,
improved-fast, and strategic implementations, producing JSON plus Markdown.
Results include deterministic violations and pairwise rubric scores; an LLM
judge alone cannot establish superiority.

Authenticated Brain operations expose configuration, privacy-safe aggregate
outcomes, recent structured decisions, gate results, memories, open threads,
and experiment summaries. They never expose keys, hidden prompts, chain of
thought, or raw conversation contents.

## Rollout gates

Production defaults are `current` mode and zero shadow sampling. Only after
local tests, migration verification, GitHub CI, exact Railway deployment,
readiness, unsigned-webhook rejection, unchanged bot state, and proven outbox
isolation may production be changed to:

- `BRAIN_MODE=shadow`
- `BRAIN_SHADOW_SAMPLE_PERCENT=10`
- `BRAIN_MAX_STRATEGIC_CALLS_PER_DAY=100`

No other production variables or secrets are changed.
