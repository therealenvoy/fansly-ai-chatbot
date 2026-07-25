# SpiralEngine Integration Plan

## Goal
Wire SpiralStateMachine into FanSession, bot.py, and dashboard. Replace linear funnel with perpetual escalation loop.

## Dependency Graph

```
SpiralStateMachine (built, tested) ──┐
                                     ├──→ FanSession ──→ bot.py ──→ Dashboard
FunnelStateMachine (keep for compat) ─┘
```

## Tasks (Vertical Slices)

### Task 1: Wire into FanSession
- Replace `FunnelStateMachine` import with `SpiralStateMachine` in `funnel/session.py`
- Map `funnel.current_stage` → `funnel.phase`
- All existing code that reads `session.funnel.current_stage` will automatically work
- Keep `.can_send_ppv()`, `.min_messages_before_tease()` — same interface
- Add `session.funnel.level`, `session.funnel.cooldown`, `session.funnel.escalation_level` for bot access

**Files:** `src/funnel/session.py`
**Verify:** `tests/funnel/test_session.py` + spiral tests

### Task 2: Wire into bot.py _generate_reply
- Replace `FunnelStage.RAPPORT` → `SpiralPhase.RAPPORT` in phase checks
- Add aftercare completion: after sending aftercare, call `funnel.complete_aftercare()` to loop back to RAPPORT
- Add cooldown routing: in `_process_chat`, if `funnel.cooldown` → use lighter tone scripts
- Add warmup: if `funnel.is_warmup` → faster re-rapport, fewer messages before tease
- Add rejection tracking: when fan declines PPV, call `funnel.record_rejection()`
- Add level: pass `funnel.escalation_level` to sequence engine for price selection
- Update imports: `from .funnel.spiral import SpiralStateMachine, SpiralPhase`

**Files:** `src/bot.py`
**Verify:** All phase-based routing still works correctly

### Task 3: Rejection + Cooldown Detection in _process_chat
- Detect when fan says no/skip/not interested → call `funnel.record_rejection()`
- If `funnel.cooldown → `use non-sexual, light scripts
- When cooldown ends (fan re-engages positively) → `funnel.exit_cooldown()`

### Task 4: Aftercare → Rapport Loop
- In `_send_aftercare`, after sending, call `funnel.transition(SpiralPhase.RAPPORT)` via `funnel.complete_aftercare()`
- This feeds back into RAPPORT at next level

### Task 5: Update Dashboard
- Add level, cooldown, phase to funnel/conversation API
- Show in fan detail drawer
- Add level badge in funnel table

## Risks
- Old FunnelStateMachine tests must still pass (other tests may import it)
- The `can_send_ppv()` interface stays identical — no risk
- `min_messages_before_tease()` stays identical — no risk