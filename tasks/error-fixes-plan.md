# Spiral Engine Bug Fixes

## Task 1: Cooldown Exit on Fan Engagement
**Problem:** Cooldown has no exit. Fan sends flirty/sexual messages but bot stays in asexual mode.
**Fix:** Detect engagement signals → exit_cooldown()
- Flirty keywords: "hard", "horny", "wet", "turn on", "hot", "sexy", "want you"
- Quick response: < 30s between messages signals eagerness
- Tip detection: any tip = exit cooldown immediately
**File:** `src/bot.py` (in _process_chat)
**Tests:** test that cooldown exits on flirty message, exits on tip
**Depends on:** nothing

## Task 2: Aftercare Phase Guard
**Problem:** AftercareEngine timer fires regardless of spiral phase. Could send aftercare when bot is already looping back to RAPPORT.
**Fix:** Only check aftercare if spiral phase is CLOSE or AFTERCARE.
**File:** `src/bot.py` (decision pipeline)
**Tests:** test that aftercare is skipped when phase is RAPPORT
**Depends on:** nothing

## Task 3: Purchase Deduplication at Startup
**Problem:** `_purchase_count_cache` starts empty. On bot restart, ALL existing fans appear to have "new purchases" → advance_level() fires for every fan.
**Fix:** Initialize cache from database at bot startup.
**File:** `src/bot.py` (in __init__ or _process_chat initialization)
**Tests:** test that cache is populated on startup, test no double-advance
**Depends on:** nothing

## Implementation Order
All three are independent — build in any order. Test each before moving to next.