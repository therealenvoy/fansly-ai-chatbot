# Implementation Plan: Zero-AI-Trace Chatting System

## Overview

Build a multi-layer humanization pipeline that scrubs every outbound message of AI tells, enriches style mirroring, and eliminates phrase repetition. Each phase is TDD: RED (failing test) → GREEN (minimal code) → REFACTOR.

## Architecture Decision

Pipeline order (enforced in `_styled_send`):
```
generate_reply() → humanizer.humanize() → style_mirror.adapt() → persona_validator.validate() → send
```

Humanizer runs FIRST because style mirror should adapt the final humanized text, not re-introduce AI patterns. Persona validator runs LAST as a safety gate.

## Task List

### Phase 1: Humanizer Core (30 patterns, 25+ tests)

- [ ] **Task 1: Pattern definitions** — `src/humanize/patterns.py`
  - Regex/string patterns for ALL 33 AI tells from the humanizer skill
  - Categorized: CONTENT, LANGUAGE, STYLE, COMMUNICATION, FILLER
  - Acceptance: every pattern has a test that proves it catches its target tell
  - Files: `src/humanize/__init__.py`, `src/humanize/patterns.py`

- [ ] **Task 2: Em dashes + punctuation** — `src/humanize/filter.py`
  - `_remove_em_dashes`: swap — and – to commas/periods
  - `_remove_curly_quotes`: “ ” → " "
  - `_remove_double_hyphens`: ` -- ` → `, `
  - Tests: 3 tests

- [ ] **Task 3: AI vocabulary scrub** — `src/humanize/filter.py`
  - Remove/replace: delve, underscore, showcase, pivotal, tapestry, vibrant (abstract), testament, crucial, enhance, foster, garner, highlight, intricate, interplay, landscape (abstract), robust, dynamic (abstract)
  - Tests: maps each banned word to a simpler replacement

- [ ] **Task 4: Fillers and hedging** — `src/humanize/filter.py`
  - `"in order to"` → `"to"`
  - `"due to the fact that"` → `"because"`
  - `"at this point in time"` → `"now"`
  - `"has the ability to"` → `"can"`
  - `"it is important to note that"` → (strip)
  - `"it could potentially possibly be"` → `"it may"`
  - Tests: 8+ fillers

- [ ] **Task 5: Structural AI tells** — `src/humanize/filter.py`
  - Copula avoidance: `"serves as"` → `"is"`, `"stands as"` → `"is"`, `"boasts"` → `"has"`
  - Negative parallelism: `"not only... but"` unwind
  - Rule of three: detect 3-item lists, condense
  - Superficial -ing phrases: strip trailing `, highlighting/underscoring/ensuring/reflecting/symbolizing/contributing`
  - Tests: 5 tests

- [ ] **Task 6: Tone and communication** — `src/humanize/filter.py`
  - Sycophantic: `"Certainly!"`, `"Of course!"`, `"You're absolutely right!"` → natural equivalents
  - Collaborative: `"Let me know if..."`, `"I hope this helps"`, `"Would you like..."`, `"Want me to...?"` → strip
  - Signposting: `"Let's dive in"`, `"Let's explore"`, `"Here's what you need to know"` → strip
  - Aphorism formulas: `"X is the Y of Z"`, `"language of"`, `"currency of"` → concrete rewrite
  - Fragmented headers: detect heading + one-line restatement → merge
  - Tests: 6 tests

- [ ] **Task 7: Contextual tells** — `src/humanize/filter.py`
  - Elegant variation (synonym cycling): detect consecutive same-subject synonyms → collapse
  - Knowledge-cutoff: `"as of 2025"`, `"up to my last update"` → strip
  - Speculative gap-fill: `"likely grew up"`, `"maintains a low profile"` → strip or rewrite
  - Persuasive authority: `"The real question is"`, `"at its core"`, `"what really matters"`, `"the deeper issue"` → simplify
  - Diff-anchored: `"was added to replace"` → present tense rewrite
  - Tests: 6 tests

- [ ] **Task 8: Humanizer pipeline integration** — `src/humanize/filter.py`
  - `humanize(text) -> str`: runs all transforms in order
  - Wire into `_styled_send`: `text = self.humanizer.humanize(text)` before mirroring
  - Config toggle: `self.humanizer_enabled = True`
  - Tests: pipeline runs all transforms, toggle works, edge case (empty string)

### ✅ Checkpoint: Phase 1 Complete
- [ ] All 33 pattern categories have tests
- [ ] All tests pass (`pytest tests/humanize/ -v`)
- [ ] Full suite passes (`pytest tests/ -q`)

### Phase 2: Variation Pools (Eliminate Repetition)

- [ ] **Task 9: Variation engine** — `src/humanize/variation.py`
  - `VariationPool`: stores 5-8 phrasings per message type
  - `pool.pick(key) -> str`: round-robin or random selection, never repeats same variant twice in a row
  - `pool.pick_with_context(key, fan_id) -> str`: fan-aware, tracks last-used per fan
  - Tests: pool cycling, no repeats, fan isolation, empty pool fallback

- [ ] **Task 10: Replace all bot.py hardcoded strings**
  - Replace rapport default (was `"Hey babe! How's your day going? 💕"`) → 8 variants
  - Replace push messages (was `"I was just thinking about you..."`) → 8 variants
  - Replace aftercare (was `"That was so fun..."`) → 6 variants
  - Replace re-engagement (was `"Hey... I haven't heard from you..."`) → 6 variants
  - Replace premium PPV offer → 6 variants
  - Replace close message → 6 variants
  - Tests: each variant pool returns unique strings, no hardcoded strings remain in bot.py

### ✅ Checkpoint: Phase 2 Complete
- [ ] No hardcoded message strings remain in bot.py
- [ ] Variation tests pass
- [ ] Full suite passes

### Phase 3: Enhanced Style Mirror

- [ ] **Task 11: Punctuation energy matching** — `src/style/mirror.py`
  - `StyleProfile.exclamation_energy`: single `!` vs `!!` vs `!!!` ratio
  - `StyleProfile.question_style`: `?` vs `??` vs `?!` 
  - `adapt()` transform: match fan's punctuation intensity
  - Tests: exclamation matching, question matching, mixed patterns

- [ ] **Task 12: Sentence length variance** — `src/style/mirror.py`
  - `StyleProfile.sentence_length_stddev`: variance metric
  - If fan uses mix of short/long sentences, vary reply sentence length similarly
  - Tests: variance detection, length randomization within bounds

- [ ] **Task 13: Greeting/sign-off matching** — `src/style/mirror.py`
  - `StyleProfile.greeting_style`: does fan open with "hey", "hi", "hello", or no greeting?
  - `StyleProfile.signoff_style`: does fan close or trail off?
  - `adapt()`: match opening/closing patterns
  - Tests: greeting detection, sign-off matching

### ✅ Checkpoint: Phase 3 Complete
- [ ] 8+ style dimensions analyzed and matched
- [ ] All style tests pass
- [ ] Full suite passes

### Phase 4: Integration & Verification

- [ ] **Task 14: Integration test** — End-to-end: raw AI-ish text → humanized → style-mirrored → output
  - Test with a representative sample of each message type
  - Verify NO em dashes, NO AI vocabulary, NO sycophantic tone in output
  - Verify style mirror adapts after humanization
- [ ] **Task 15: Deployment** — Deploy #19 to Railway
- [ ] **Task 16: Production verification** — Spot-check live bot messages for AI tells, adjust patterns

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Humanizer over-corrects → messages sound unnatural | Medium | Each pattern has a tested replacement, not just deletion |
| Style mirror + humanizer conflict | Low | Order is fixed: humanizer first, then mirror |
| Variation pools run out → repeats | Low | 6-8 variants per pool, random selection with fan tracking |
| Regex misses edge cases | Low | Tests cover boundary cases per pattern |

## Open Questions

- (None — spec is complete)