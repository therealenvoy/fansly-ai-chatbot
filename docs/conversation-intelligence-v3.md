# Conversation Intelligence V3

Conversation Intelligence V3 extends Brain 2.0. It is not a second delivery
pipeline. When explicitly granted live decision authority, it may select the
candidate returned to the existing durable inbox/outbox pipeline.

## Authority boundary

The V3 service receives an already-authenticated, creator-scoped inbound turn
after the durable Brain 2.0 pipeline owns it. V3 may write only:

- reviewed knowledge revisions and their page evidence;
- isolated shadow or live fan-state transitions and callback metadata;
- privacy-safe candidate fingerprints and aggregate run telemetry;
- attributable operator feedback.

It cannot write to `outbox_messages` or call a Fansly provider. Live selection
requires every core V3 component to have a `live` environment ceiling,
`CONVERSATION_INTELLIGENCE_V3_ALLOW_SEND=true`, and a non-zero effective live
percentage bounded by `CONVERSATION_INTELLIGENCE_V3_MAX_LIVE_PERCENT`. Only
authenticated inbound text turns are eligible. Proactive, PPV, media, and
multi-bubble work is excluded. If V3 fails or its final gates reject the
candidate, the current Brain pipeline remains the fallback. A positive
`CONVERSATION_INTELLIGENCE_V3_MAX_DAILY_COST` is also required; the live V3
path fails closed when that UTC-day ceiling is reached or cannot be read.

## Turn flow

1. Combine the newest fan bubbles through the existing inbound debounce.
2. Reduce evidence-backed relationship state with hysteresis and decay.
3. Retrieve 8–12 active source-backed memories and at most two eligible
   callbacks. Contradicted, expired, inactive, or cooling-down items are
   excluded. Selecting a callback for a shadow draft never advances its
   cooldown; only a future confirmed live send may do that.
4. Retrieve applicable boundaries, 3–6 approved conversation or relationship
   rules, and 2–4 structurally diverse examples. Sales-profile material is
   excluded from reply context.
5. Compile context in this fixed priority: safety, newest turn, unresolved
   direct question, recent history, relationship state, boundaries, verified
   creator facts, memories, playbook rules, examples, callbacks, persona,
   creator instructions, diversity context.
6. Route ordinary turns to one Flash call that returns two genuinely different
   candidates. Strategic turns may use a second Flash judge call and at most
   one replacement candidate.
7. Apply deterministic direct-question, grounding, policy, per-fan diversity,
   and creator-wide diversity gates.
8. If all candidates fail, acknowledge only an explicit boundary or correction
   when that response is deterministically grounded. Otherwise record an
   operator-review state. Generic emergency filler is not allowed.
9. Store the shadow or live plan, version fingerprints, rejection codes,
   latency, token usage, estimated cost, and privacy-safe candidate
   fingerprints.
   Eligible inbound turns are observed even when the current reply pipeline
   returns no approved reply, so silent failures remain measurable.

## Knowledge governance

PDF extraction is local, page-aware, fingerprinted, cached, and limited to
25 MB and 1,000 pages. External OCR is never invoked automatically. An owner
reviews source-backed rules and examples before activation. Activating a new
revision archives the prior active revision of that document type; history is
never overwritten, and rollback is explicit. PostgreSQL full-text search is
used for approved rule retrieval. Embeddings are intentionally absent until
the frozen suite demonstrates a retrieval failure that full-text search cannot
solve.

## Fan Brain governance

Memories retain their exact source message and timestamp, confidence,
importance, sensitivity class, contradiction key, expiry, and status. A
correction creates a superseding fact; it does not rewrite the original.
Deactivation immediately removes a fact from future retrieval. Callback reuse
has a seven-day standard cooldown and a thirty-day sensitive cooldown.

Only the owner can access Knowledge Center, Fan Brain, Quality Lab, Brain
settings, or memory mutation APIs. The posting VA is denied before those
handlers run.

## Evaluation and promotion

The frozen suite contains 204 synthetic, sanitized cases across 17 scenarios.
The aggregate evaluator fails closed unless every case appears exactly once
with reviewer evidence. Frozen gates require:

- newest-turn relevance at least 95%;
- zero unsupported creator facts, ignored direct questions, and safety
  failures;
- repeated structures below 5%, generic openings below 3%, unnecessary
  question endings below 20%, and generic fallback below 1%;
- P50 latency below 3 seconds and P95 below 7 seconds;
- one model call on fast turns, at most two on strategic turns, and zero
  implicit DeepSeek Pro usage;
- at least 200 blinded reviews, at least 150 decisive reviews, at least 65%
  candidate preference, and zero safety regressions.

Passing frozen gates does not itself authorize a promotion. Live authority is
an explicit operator and deployment decision. A three-consecutive-failure
runtime circuit fails back to the current Brain pipeline without granting V3
any outbox or provider capability.

## Tiffany training release

`tiffany-training-v1` is compiled deterministically from the owner-approved
Parts 00, 01, 02, and 04-10. Part 03 is intentionally excluded. The compiler
produces ten versioned source documents, source-page rules, paired positive and
negative examples, the Part 09 memory policy, and the Part 10 feedback schema.
Negative examples are stored only as contrastive anti-examples and are never
selected as positive response demonstrations.

The artifact fingerprint covers every source-backed document, rule, example,
and runtime policy. Ingestion validates that fingerprint and stores the release
atomically for one creator. The default ingestion mode is `shadow`: live
retrieval excludes every document belonging to that release, while shadow
evaluation may retrieve it. Promotion to `active` is a separate explicit
operation. Repeated ingestion of the same version is idempotent; reusing a
version with different content fails closed. Prior releases remain archived
for rollback. Corpus ingestion cannot create an outbox row or call a provider.

Runtime prompts do not contain the entire corpus. Retrieval contributes only
the relevant rule guidance, boundaries, examples, non-quotable memory controls,
and release identity for the current turn. This keeps prompt size bounded while
making every choice traceable to an approved source page.

When the active release supplies Part 09, memory categories become an allowlist.
Low-confidence or unknown categories are excluded. Contextual memories require
current-turn relevance. Operator-only memories such as boundaries, corrections,
sensitivities, and style preferences become non-quotable generation controls
rather than facts the bot may repeat.

## Multi-bubble delivery

The existing Human Delivery foundation owns durable plans, bubble sequencing,
debounce, idempotency, and cancellation. V3 may propose inert bubble
boundaries, but multi-bubble delivery remains disconnected. Creator/manual
sends, a newer fan turn, deletion, bot disablement, or provider reconciliation
cancel stale unsent bubbles before any future live integration is considered.
