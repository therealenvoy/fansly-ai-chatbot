# Todo: Bot On/Off Toggle

## Phase 1: Foundation

- [ ] Task 1: SettingsStore — key-value persistence table + tests
  - Acceptance: `get()`/`set()` work, values survive across instances
  - Verify: `pytest tests/test_settings.py -v` — 6/6 pass

- [ ] Task 2: FanslyBot enabled flag + guard + toggle method + tests
  - Acceptance: `poll_and_process()` returns early when `enabled=False`, `toggle()` flips state
  - Verify: `pytest tests/test_bot.py -v` — 5/5 pass

### Checkpoint: Foundation
- [ ] `pytest tests/ -q` — all existing + new tests pass
- [ ] Review with human before proceeding

## Phase 2: Integration

- [ ] Task 3: Wire SettingsStore into main.py — init flag from DB on startup
  - Acceptance: Bot reads `bot_enabled` from DB, logs the state
  - Verify: Manual run logs "Bot enabled state from DB: True"

- [ ] Task 4: Dashboard API endpoints — `GET /api/bot/status` + `POST /api/bot/toggle`
  - Acceptance: Status returns `enabled: true/false`, toggle flips and persists
  - Verify: `curl localhost:8080/api/bot/status` returns `{"enabled": true}`

- [ ] Task 5: Dashboard UI — clickable toggle pill in sidebar
  - Acceptance: Green pill shows ON/OFF, click toggles instantly, no page reload
  - Verify: Manual click in browser

### Checkpoint: Integration
- [ ] Full test suite passes
- [ ] Toggle button visible and functional in browser
- [ ] Toggle persists across container restart
- [ ] `/health` reports `bot_enabled`

## Phase 3: Polish

- [ ] Task 6: Verify /health endpoint includes bot_enabled field
  - Acceptance: `curl localhost:8080/health` returns `{"bot_enabled": true/false}`
  - Verify: curl command

### Done
- [ ] All tests pass
- [ ] All acceptance criteria met
- [ ] Ready for deploy