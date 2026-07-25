# Spec: Bot On/Off Switch + Fansly API Client Adapter

## Objective

Two things:

1. **On/Off switch** — Add a button to the dashboard that pauses/resumes the bot instantly. Survives restarts. The bot stops processing messages when off, resumes when on. Accessible from the dashboard home page.

2. **Fansly API Client Adapter** — Rewrite `fansly_client.py` to support both apifansly.com and fansly-api.com behind a common interface. Swap providers by changing one env var.

## Tech Stack

Same as existing: Python 3.11, httpx, SQLite/Postgres, raw HTTP server

## Commands

Test: `cd /opt/data/fansly-ai-chatbot && python3 -m pytest tests/ -q`
Run: `cd /opt/data/fansly-ai-chatbot && python3 -m src.main`

## Project Structure (changes)

```
src/
├── fansly_client.py        ← REFACTOR: adapter pattern (FanslyClient ABC + 2 implementations)
├── bot.py                   ← ADD: bot.enabled flag, enabled/disabled check in poll
├── main.py                  ← ADD: read bot_enabled from DB on startup
├── web/
│   └── dashboard.py         ← ADD: /api/bot/status GET, /api/bot/toggle POST, toggle button in HTML
│   └── templates/           ← if needed for HTML
```

## Code Style

```python
# FanslyClient adapter
from abc import ABC, abstractmethod

class FanslyClient(ABC):
    @abstractmethod
    def get_all_chats(self, filter_type: str = "all") -> list[ChatInfo]: ...
    @abstractmethod
    def send_message(self, chat_id: str, text: str) -> SentMessage: ...

class ApifanslyClient(FanslyClient):
    """Original implementation for apifansly.com - Bearer token"""
    ...

class FanslyApiClient(FanslyClient):
    """New implementation for fansly-api.com"""
    ...
```

```python
# Bot toggle
class FanslyBot:
    def __init__(self, ...):
        self.enabled: bool = True  # Can be changed at runtime
    
    def poll_and_process(self):
        if not self.enabled:
            return  # No-op when disabled
        ...
```

## Testing Strategy

- Unit tests for toggle: `test_bot_starts_enabled`, `test_bot_skips_poll_when_disabled`, `test_toggle_persists_to_db`
- Integration test for FanslyApiClient (when API key with Fansly account is available)
- All 420+ existing tests must pass

## Boundaries

- **Always:** TDD, run full suite before merge
- **Ask first:** Changing the dashboard threading model (already flagged as needed)
- **Never:** Remove existing API client until new one is fully tested

## Success Criteria

- [ ] Dashboard has an ON/OFF button that toggles the bot instantly
- [ ] Toggle state survives bot restart (persisted to DB)
- [ ] When OFF, bot does not process ANY messages (poll is no-op)
- [ ] When ON, bot resumes normal operation
- [ ] FanslyApiClient works with provided key (once Fansly account is connected)
- [ ] 420+ tests pass

## Open Questions

- Where exactly in the dashboard should the toggle button live? (Top-right corner, like a power button)
- Should toggle be per-account (for multi-account future) or global? (Start global)
- What visual state should it show? (Green/gray pill button)