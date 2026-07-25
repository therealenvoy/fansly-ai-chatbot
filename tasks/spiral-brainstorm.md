# Spiral Engine: Stress Test & Expansion

## Doubt-Driven: What Breaks?

### 1. Cooldown has no exit door (critical bug)
Fan rejects 2 PPVs → cooldown activates. Bot stays in light rapport. Fan sends a horny message "I'm so hard thinking about you" — but the bot stays in cooldown and ignores it. The fan gets frustrated because the bot won't escalate with them.
**Fix:** Detect flirty/horny keywords → exit_cooldown() immediately

### 2. Aftercare phase vs aftercare engine conflict
We have TWO aftercare systems now:
- AftercareEngine (check timers, send appreciation message)
- SpiralPhase.AFTERCARE (phase transition management)
They don't talk to each other. AftercareEngine might say "send aftercare" while the spiral is still in OFFER phase.
**Fix:** Unify: only check aftercare engine when spiral is in CLOSE or AFTERCARE phase

### 3. Warmup changes required messages but not bot tone
Warmup reduces min_messages_before_tease to 1. But the bot still says the same rapport messages. Warmup should use softer, more "welcome back" language.
**Fix:** Add warmup-aware routing in _generate_reply

### 4. Ghost during aftercare
Fan buys PPV, enters CLOSE → AFTERCARE. But fan goes silent for 3 days. The aftercare timer fires, sends "that was so fun" — but fan doesn't respond. Spiral stays stuck in AFTERCARE.
**Fix:** After aftercare is sent + fan doesn't respond in 24h, auto-complete aftercare and loop to RAPPORT

### 5. Spiral phase can drift from reality
Level increases on purchase detection. But what if purchase_detected is called multiple times for the same purchase? Level could inflate.
**Fix:** Deduplicate: only advance_level() once per unique purchase_count increment

### 6. No dashboard warmup/cooldown visibility
User can't see which fans are in cooldown (aside from the snowflake icon) or warmup. They fly blind.
**Add:** Warmup indicator, cooldown expiry estimate in fan detail drawer

## Idea-Refine: What's Missing?

### 7. Soft cooldown exit via positive interaction
Not just flirty keywords — also: fan sending a longer message, fan responding quickly, fan tipping. These all signal re-engagement.

### 8. Emotional state as cooldown override
If fan emotional state is HORNY/EXCITED → cooldown should auto-exit. Emotional state > cooldown.

### 9. Level-aware scripts
At level 0 (first sell), bot uses "made this just for you" framing.
At level 3+ (return buyer), bot uses "remember last time you loved this..." framing.

### 10. Aftercare seeds the NEXT level purchase
Aftercare message should hint at what's coming next:
Level 0 → aftercare: "that was fun... wait until you see what I prepared next 😈"
Level 2 → aftercare: "you keep getting hotter... I'm not sure you're ready for what I have planned"

## Priority Order

P0 (needed now, bug):
- Cooldown exit on flirty/fast responses
- Unify aftercare engine with spiral phase (don't send aftercare if already looping)

P1 (should build now):
- Warmup-aware bot language
- Ghost-during-aftercare timeout
- Purchase deduplication

P2 (next session):
- Level-aware scripts
- Dashboard visibility for warmup/cooldown
- Emotional state detection
