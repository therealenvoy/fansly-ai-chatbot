# Spec: Bot On/Off Toggle Switch

## Objective

Add a one-click on/off toggle button to the dashboard sidebar that instantly enables or disables the Fansly bot. When off, the bot skips all API polling and message processing — no API credits consumed, no replies sent. The toggle persists across restarts.

**User story:** "I want a button to turn the bot off when I'm manually chatting, and back on when I'm done — without redeploying."

## ASSUMPTIONS

1. Bot state persists via a `bot_settings` key-value table in the existing DB (SQLite/Postgres)
2. The toggle sits in the sidebar header, next to the green dot — visible from every dashboard tab
3. When off, `poll_and_process()` returns immediately — zero API calls, zero processing
4. The toggle is instant (no page reload) — AJAX POST toggles, UI updates immediately
5. Tests use pytest with existing patterns (`tests/test_bot.py`)

## Tech Stack

- Python 3.11+, SQLite/Postgres (via SQLAlchemy)
- Built-in `http.server` (no framework)
- Inline JS (no build step)
- pytest for testing

## Commands

```bash
# Full test suite
pytest tests/ -q

# Run specific test
pytest tests/test_bot.py::test_bot_enabled_by_default -v

# Start bot
python -m src.main

# Lint
python -m py_compile src/bot.py src/web/dashboard.py
```

## Project Structure (relevant files only)

```
src/
  bot.py              → FanslyBot.enabled flag + guard in poll_and_process()
  web/dashboard.py    → API endpoint + sidebar toggle button in HTML
  settings/           → NEW: settings module
    __init__.py
    store.py          → NEW: SettingsStore (key-value, SQLAlchemy)
tests/
  test_bot.py         → NEW: bot toggle tests
  test_settings.py    → NEW: settings store tests
```

## Code Style

```python
# Style: flat, no indirection. Simple flag + guard.
class FanslyBot:
    def __init__(self, ...):
        self.enabled = True  # default on


    def poll_and_process(self, ...):
        if not self.enabled:
            logger.debug("Bot disabled — skipping poll cycle")
            return
        # ... existing logic
```

## Testing Strategy

| Test | What it covers |
|------|---------------|
| `test_bot_enabled_by_default` | `FanslyBot.enabled == True` on init |
| `test_bot_skips_poll_when_disabled` | `poll_and_process()` returns early when `enabled=False` |
| `test_bot_processes_when_enabled` | `poll_and_process()` calls `client.get_all_chats()` when enabled |
| `test_settings_store_set_and_get` | SettingsStore.set("key", "val") and .get("key") |
| `test_settings_store_persists` | Values survive store re-initialization |
| `test_bot_loads_enabled_from_db` | Bot reads initial state from DB on startup |
| `test_api_toggle_endpoint` | POST /api/bot/toggle toggles and returns new state |
| `test_api_bot_status_endpoint` | GET /api/bot/status returns enabled state |

## Boundaries

- **Always do:** Check `enabled` flag before ANY API call in `poll_and_process()`
- **Always do:** Initialize flag from DB on startup (default: `True`)
- **Always do:** Use TDD — test before implementation for every task
- **Ask first:** Adding new dependencies, changing DB schema
- **Never do:** Toggle requiring restart, storing state only in memory

## Success Criteria

- [ ] Green dot in sidebar header becomes a clickable toggle pill
- [ ] Clicking toggle instantly disables/enables bot (no page reload)
- [ ] When disabled, `poll_and_process()` uses zero API credits
- [ ] State persists across container restarts
- [ ] All 8+ tests pass
- [ ] Health endpoint (`/health`) reports `bot_enabled: true/false`

## Open Questions

- [ ] Should we add a visual indicator in the poll loop logs when disabled? (Yes — log once on transition, not on every poll cycle)