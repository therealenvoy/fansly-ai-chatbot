# Spiral Funnel Engine — The Bot Never Stops Looping

## The Core Problem With Our Bot

We have a **linear** 5-stage funnel. Rapport → Tease → Offer → Handle → Close. Once it hits Close, it's DONE. The bot has no concept of re-entering the loop at a higher level.

## The Spiral Model (0.00001% Chatter Behavior)

```
                ┌───────────────────────────────────────────────────────┐
                │                                                       │
                │  Level 1:     Level 2:     Level 3:     Level N:      │
                │  $3-5          $8-12        $15-25      $50+           │
                │                                                       │
                │  Rapport 1 →  Rapport 2 →  Rapport 3 →  Rapport N     │
                │     ↓             ↓             ↓            ↓         │
                │  Tease 1      Tease 2      Tease 3       Tease N      │
                │     ↓             ↓             ↓            ↓         │
                │  Offer 1      Offer 2      Offer 3       Offer N      │
                │     ↓             ↓             ↓            ↓         │
                │  Handle 1     Handle 2     Handle 3      Handle N     │
                │     ↓             ↓             ↓            ↓         │
                │  Close 1 ─→ Aftercare 1 ─→ Close 2 ─→ ─→ Close N     │
                │     │                                                    │
                │     └──────── Aftercare seeds NEXT level ──────────────┘
                │                                                       │
                │  Each cycle: deeper rapport, bigger ask, more intense  │
                └───────────────────────────────────────────────────────┘
```

**Key insight:** Top chatters don't "close" — they **escalate**. Every close is actually a setup for the next, bigger close. Aftercare isn't the end — it's the beginning of the next cycle.

---

## Architecture Changes Needed

### 1. Replace Linear Funnel with Spiral State Machine

**Current:** `FunnelStage` enum with 5 values + `can_send_ppv()` boolean.
**New:** `SpiralEngine` that tracks:
- `escalation_level` (0-N, increments on each purchase)
- `cycle_phase` (RAPPORT → TEASE → OFFER → HANDLE → CLOSE → AFTERCARE → back to RAPPORT)
- `emotional_state` of the fan (EXCITED, HESITANT, FATIGUED, LONELY, HORNY)
- `fatigue_score` (how hard the fan has been pushed recently)

**Behavior at Close:** Instead of staying at Close, automatically transition to:
1. Aftercare (5-10 min delay)
2. Aftercare follow-up (24h)
3. Back to RAPPORT at next escalation level

### 2. Escalation-Aware Sequence Engine

**Current:** Get next PPV based on funnel stage and progress position.
**New:** Each Sequence has an `escalation_level` — multiple sequences at different levels.

```python
# At level 1: offer the $3-5 sequence
# At level 2: offer the $8-12 sequence  
# At level 3: offer the $15-25 sequence
# No level-matched sequence? Create one automatically by scaling price
```

### 3. Emotional State Detection

**What it does:** Every time a fan sends a message, classify their emotional state from text.

**Implementation:**
- Simple keyword + sentiment analysis on each fan message
- States: EXCITED, HESITANT, FATIGUED, LONELY, HORNY, GUILTY, CURIOUS
- Each state routes to different behavior:
  - HESITANT → softer approach, validate concerns
  - FATIGUED → cool-down (light chat, no offers for 1-3 days)
  - HORNY/EXCITED → faster escalation, bigger ask
  - LONELY → more rapport, less sales energy

### 4. Fatigue System

**What it does:** Prevents the bot from burning out fans by tracking how hard they've been pushed.

**Metrics:**
- Offers sent in last 24h
- Purchase frequency
- Response length trend (longer = engaged, shorter = tired)
- Time between messages

**When fatigue is high:**
- Enter "cool-down" mode: light chat only, no offers for 1-3 days
- Send free content (rebuilds reciprocity for next cycle)
- After cool-down: re-enter at current level, not reset

### 5. Content Funnel (Sequence-to-Sequence Chaining)

**Current:** Each sequence is independent.
**New:** Sequences can chain into each other.

```python
# Sequence A: "Welcome Ladder" (level 1, $3-8)
# After completing A → automatically activate Sequence B: "Getting Hotter" (level 2, $8-15)
# After completing B → automatically activate Sequence C: "Deep Fantasy" (level 3, $15-30)
```

### 6. Multi-Thread Selling

**Current:** One sequence at a time.
**New:** A fan can be in multiple sequences simultaneously — different content themes, different escalation paths.

Example:
- Fan is in "Feet Content" sequence (their primary kink) at level 2
- Also in "General Content" sequence at level 1
- Both advance independently as the fan buys from each

### 7. Contextual Anchoring

**What it does:** When a fan buys, the bot records the exact conversational context (what the fan was excited about, what they said). Next time the bot escalates, it references that context to recreate the buying state.

**Implementation:**
- Before sending each PPV, store: fan's last 3 messages, what they responded positively to
- Next PPV: "Remember last time when you said you loved X? This is even better..."

---

## Implementation Phases

### Phase 1: Spiral State Machine (core architecture)
- Replace FunnelStage enum with SpiralEngine (escalation_level + cycle_phase)
- Wire Close → Aftercare → Rapport loop
- Fatigue detection (simple version: offer count in 24h)
- After closing a purchase, automatically advance to next level

### Phase 2: Sequence Chaining
- Sequences get `next_sequence_id` field
- Completing one sequence auto-activates the next at higher price tier
- Dashboard: when editing sequence, "Chain to:" dropdown

### Phase 3: Emotional State Detection
- Classify each fan message into emotional state
- Route to different behaviors per state
- Dashboard: show current emotional state per fan

### Phase 4: Contextual Anchoring
- Store purchase context
- Inject into next PPV script
- "You really loved that last one... wait until you see this"

### Phase 5: Multi-Thread + Cool-Down
- Allow multiple active sequences per fan
- Fatigue-based cool-down periods
- Automatic re-engagement after cool-down

## What Makes This 0.00001% (Not Generic)

| Generic | 0.00001% |
|---------|----------|
| Linear funnel ends at Close | Spiral loops forever, each cycle deeper |
| One price per fan forever | Escalating prices per cycle |
| No emotional awareness | Tracks excitement, fatigue, hesitation separately |
| Sequence is one-and-done | Sequences chain into higher-tier sequences |
| Aftercare = thank you | Aftercare = setup for next bigger purchase |
| Same cadence for everyone | Dynamic pace based on fatigue + emotional state |
| Ignores what fan said during purchase | Anchors next offer in their own words |
| One sequence at a time | Multiple sequences per fan (multi-kink) |
| Sales = interrupting rapport | Sales ARE the rapport (every message builds toward next) |