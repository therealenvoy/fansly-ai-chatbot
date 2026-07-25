# Implementation Plan: Bot Toggle + API Adapter

## Overview

Two parallel workstreams:

1. **Bot Toggle** — Simple, dashboard-accessible on/off switch. Build in TDD order: tests → settings store → bot.enabled → dashboard button.

2. **FanslyApiClient** — New adapter implementation for fansly-api.com. The interface is already defined by the existing code. This is a pure "implement the interface" task.

## Dependency Map

```
Bot Toggle                          API Adapter
    │                                      │
    ├── settings_store.py                  ├── fansly_client.py (add FanslyApiClient)
    ├── bot.py (add enabled flag)           ├── tests/test_fansly_api_client.py
    ├── web/dashboard.py (toggle button)    └── fansly_client.py (add PROVIDER config)
    ├── main.py (init from DB)
    └── tests/test_toggle.py
```

## Task List

### Phase 1: Bot Toggle

- [ ] **Task 1: Settings Store** — `src/settings/store.py`
  - `BotSettings` dataclass with `bot_enabled: bool = True`
  - `SettingsRepository` with `get(key)`, `set(key, value)` backed by SQLite/Postgres
  - Initializes `bot_settings` table on startup
  - Tests: CRUD, default value, persistence across instances
  
- [ ] **Task 2: Bot enabled flag** — `src/bot.py`
  - `FanslyBot.enabled` attribute (bool, default True)
  - `poll_and_process()` returns early if `not self.enabled`
  - `set_enabled(bool)` method
  - Tests: starts enabled, skips poll when disabled, can toggle

- [ ] **Task 3: Dashboard toggle** — `src/web/dashboard.py`
  - `GET /api/bot/status` → `{"bot_enabled": true/false, "status": "running"/"paused"}`
  - `POST /api/bot/toggle` → toggles and returns new state
  - Toggle button UI: round pill button, green when ON, gray when OFF
  - Button hits `/api/bot/toggle` via fetch, updates UI without page reload
  
- [ ] **Task 4: Main.py integration** — `src/main.py`
  - On startup, read `bot_enabled` from settings store
  - Pass `enabled` flag to `FanslyBot.__init__` after initializing settings
  - Poll loop works as before but bot skips internally when disabled

### ✅ Checkpoint 1
- [ ] Dashboard shows ON/OFF button
- [ ] Clicking toggles instantly
- [ ] State survives restart
- [ ] All tests pass

### Phase 2: FanslyApiClient Adapter

- [ ] **Task 5: Abstract FanslyClient** — `src/fansly_client.py`
  - Convert existing class to ABC with abstract methods
  - Rename existing to `ApifanslyClient`
  - Common response models stay shared
  
- [ ] **Task 6: FanslyApiClient** — `src/fansly_client.py`
  - Implements all abstract methods
  - Uses `Bearer` auth with `ofapi_...` key
  - Base URL: `https://app.onlyfansapi.com/api`
  - Response parsing based on actual API responses (from /api/accounts pattern)
  - Error handling: 401→AuthError, 402→PaymentRequiredError (reuse existing hierarchy)
  
- [ ] **Task 7: Provider selection** — `src/main.py`
  - `FANSLY_PROVIDER` env var: `"apifansly"` (default) or `"fanslyapi"`
  - Instantiates correct client class
  
### ✅ Checkpoint 2
- [ ] Both clients implement same interface
- [ ] Provider swapped by env var
- [ ] Bot works with apifansly.com unchanged
- [ ] FanslyApiClient ready for testing when account connected

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| FanslyApiClient endpoint paths unknown until account connected | Med | Build stub + test scaffolding now; fill paths when account is available |
| Toggle DB table conflicts with existing schema | Low | Use separate table name `bot_settings` with simple key-value |
| Dashboard threading blocks toggle requests | Low | Toggle is instant (no blocking) — returns immediately |