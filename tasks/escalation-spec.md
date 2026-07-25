# Spec: Perpetual Escalation Engine

## Objective
Replace the linear 5-stage funnel (Rapport→Tease→Offer→Handle→Close→DONE) with an infinite spiral: each purchase feeds into the next cycle at a higher intensity/price level. The bot never stops selling — it just escalates or pauses.

## Core Architecture

### 1. SpiralStateMachine (replaces FunnelStateMachine)

```
State: IDLE → RAPPORT → TEASE → OFFER → HANDLE → CLOSE → AFTERCARE → (loop back to RAPPORT at level+1)
```

Key differences from current funnel:
- **Level** (int): tracks escalation depth. Starts at 0. Increments on each purchase.
- Each level affects: price ceiling, content intensity, rapport depth
- **Fatigue counter**: if fan rejects/skips 2 PPVs in a row, enter COOLDOWN state (light chat only, 1-3 days, no offers)
- **Ghost timer**: if fan stops responding for 48h+, next interaction starts at WARMUP (re-rapport without resetting level)

### 2. Escalation-Aware Price System

Each SequenceStep gets:
- `price_low: float` — minimum price for this step
- `price_high: float` — maximum price for this step  
- `intensity_level: int` — how intense/deep this content is (1-10)

Bot logic:
- First offer at `price_high` (anchor high)
- On "too expensive": negotiate down to `price_low`, never below
- On "I'm broke": offer lowest step price, mark fan budget-sensitive
- Next cycle: if budget-sensitive, start offers lower in range

### 3. Emotional State Routing

Classify each fan message into an emotional state:
- **HORNY** → escalate quickly, bigger ask, deeper content
- **LONELY** → more rapport, slower pace, smaller asks
- **EXCITED** → capitalize immediately, offer next PPV
- **HESITANT** → validate concerns, smaller ask, change angle
- **FATIGUED** → enter cooldown, light chat only
- **GHOST** → after 48h silence, resume with warmup at same level

### 4. Aftercare → Escalation Trigger

After every purchase:
1. Wait 5-10 min → send appreciation (current behavior)
2. Within 24h → send follow-up that SEEDS the next PPV:
   - "That was so hot... I have something even filthier if you're ready for it"
   - "You really liked that foot thing... wait until you see what I shot today"
3. After 24h follow-up → automatically re-enter RAPPORT at level+1

### 5. Fantasy Deepening

Bot maintains a `fantasy_arc` per fan:
- Tracks: what content they bought, what they said they liked, kinks mentioned
- Each step in the sequence should be more intense/more specific to their kinks
- If fan hasn't disclosed preferences, ask during warmup cycles
- Never repeat the same type of content at the same intensity

## Key Design Decisions

1. **One sequence per fan** — steps are ordered, bot advances sequentially
2. **Level = PPV# purchased** — level 0 = never bought, level 1 = 1 PPV bought, etc.
3. **Each step has a price range, not a fixed price** — bot can negotiate within range
4. **Fatigue = 2 skipped/rejected PPVs in a row** → cooldown mode
5. **Ghost = 48h+ no response** → warmup on return, no level reset
6. **Emotional state detected from fan message text**
7. **Aftercare always seeds the next higher offer**

## Not Doing

- Multi-threaded sequences (one at a time is enough)
- Complex AI emotion detection (keyword + sentiment is fine)
- External whale detection tools
- Custom content pipeline (too complex for now)

## Implementation Phases

### Phase 1: SpiralStateMachine + Level System
Files: src/funnel/spiral.py, tests/funnel/test_spiral.py
- New SpiralStateMachine class (level + cycle_phase)
- Replace FunnelStage enum with combined state
- Aftercare automatically re-enters at next level
- Fatigue detection (2 rejections = cooldown)

### Phase 2: Price Negotiation System
Files: src/scripts/negotiation.py, tests/scripts/test_negotiation.py
- Steps get price_low/price_high fields
- DB migration for new columns
- Negotiation engine: anchor high, negotiate down, never below floor
- Budget-sensitive tagging persists in FanNote

### Phase 3: Emotional State Detection
Files: src/nlp/emotion.py, tests/nlp/test_emotion.py
- Classify fan messages into states
- Route bot behavior per state
- Dashboard: show current emotional state per fan

### Phase 4: Fantasy Arc + Contextual Anchoring
Files: src/nlp/fantasy.py, tests/nlp/test_fantasy.py
- Track fantasy_arc per fan
- Each PPV step references previous purchases
- "Remember when you said you loved X..."

### Phase 5: Wire Everything + Dashboard
- Connect spiral system to bot.py
- Replace FunnelStage imports
- Dashboard shows level, cycle phase, emotional state
