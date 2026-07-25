# Spec: API Readiness & Production Hardening

## Objective

Fix all 5 Critical + 8 Required issues identified in the adversarial audit so the bot can connect to a real Fansly API without crashing, spamming fans, or burning money.

**Success criteria:**
- Bot can run 24/7 against a live Fansly API without errors
- No message is ever replied to more than once (C1 fix)
- API errors are categorized and handled appropriately (C2, C5, R1)
- Response parsing is resilient to shape changes (C3)
- Media uploads work end-to-end (C4)
- Credit usage is monitored and logged (R2)
- Exponential backoff prevents hammering on outages (R4)
- .env.example exists with all variables documented (R8)
- All 458 existing tests still pass + new tests for fixes

## Tech Stack

- Python 3.11, httpx, pytest, asyncio (unchanged)

## Commands

- Test: `cd /opt/data/fansly-ai-chatbot && python3 -m pytest tests/ -q`
- Run: `cd /opt/data/fansly-ai-chatbot && python3 -m src.main`

## Project Structure (changes)

```
src/
├── fansly_client.py     ← HEAVILY refactored
├── bot.py                ← message dedup tracking added
├── main.py               ← auth check + backoff + credit logging
└── web/
    └── dashboard.py      ← threading fix
.env.example              ← NEW
tests/
├── test_fansly_client.py ← NEW — API client unit tests
└── humanize/             ← existing, unchanged
```

## Code Style

All new methods use the existing patterns:
- Error handling via custom exceptions or structured error returns
- TDD: write test → watch fail → implement → watch pass
- Every API client method has a corresponding unit test

## Testing Strategy

- Unit tests for `_request()`: error categorization, retry logic, response parsing
- Unit tests for message dedup: `_has_processed()`, `_mark_processed()`, edge cases
- Unit tests for auth check startup logic
- Integration test for exponential backoff
- All existing 458 tests must still pass

## Boundaries

- **Always:** TDD, run full test suite before merge, handle all 4xx/5xx status codes
- **Ask first:** Changing API response parsing logic (may break other endpoints)
- **Never:** Add new dependencies, remove existing error handling

## Open Questions

- What's the actual Fansly API response shape? The current `data["data"]["data"]["response"]` is based on docs.apifansly.com — should verify against a real response.