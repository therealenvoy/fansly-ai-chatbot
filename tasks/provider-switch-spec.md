# Spec: API Provider Switch — apifansly.com → fansly-api.com

## Objective

Swap the API provider from **apifansly.com** (depleted credits, 35 endpoints, 12-day-old company) to **fansly-api.com** (5+ years, 200+ endpoints, webhooks, user has credits). Bot code never changes — adapter pattern.

## ASSUMPTIONS

1. **fansly-api.com auth**: Bearer token (from `app.onlyfansapi.com`), not `x-api-key` header
2. **Base URL**: `https://api.fansly-api.com/v1` (need to verify with user's key)
3. **Webhooks**: HMAC-SHA256 signed, rich events — we'll build the receiver
4. **Env var**: `FANSLY_PROVIDER=apifansly|fanslyapi` switches between them
5. **Current `FanslyClient`** class becomes `ApifanslyClient` behind an abstract base
6. **Bot never changes** — it only knows about the abstract interface

## Tech Stack

- Python 3.11+, httpx (already used)
- Abstract Base Class (`abc.ABC`) for the client interface
- pytest for TDD

## Commands

```bash
# Test new client
pytest tests/test_fansly_api_client.py -v

# Test nothing broke
pytest tests/test_bot.py tests/test_settings.py -q

# Full suite
pytest tests/ -q
```

## Project Structure (changes)

```
src/
  fansly_client.py        → MODIFY: extract ABC, rename to ApifanslyClient
  fansly_api_client.py    → NEW: FanslyApiClient (same interface, different API)
  bot.py                  → NO CHANGE needed
  web/dashboard.py        → NO CHANGE needed
  webhook/                → NEW: webhook receiver
    __init__.py
    receiver.py
tests/
  test_fansly_api_client.py   → NEW: TDD tests
```

## Code Style

```python
class FanslyApiClient(ABC):
    """Abstract base — bot only knows this interface."""
    @abstractmethod
    def get_all_chats(self, ...) -> list[ChatInfo]: ...
    @abstractmethod
    def list_messages(self, ...) -> tuple[list[MessageInfo], int]: ...
    @abstractmethod
    def send_message(self, ...) -> str: ...
    @abstractmethod
    def send_ppv(self, ...) -> str: ...
    @abstractmethod
    def upload_media(self, ...) -> str: ...
    @abstractmethod
    def list_albums(self, ...) -> list[dict]: ...
    @abstractmethod
    def get_album_media(self, ...) -> tuple[list[dict], int]: ...
    @abstractmethod
    def close(self): ...

class ApifanslyClient(FanslyApiClient):
    """Existing apifansly.com implementation — unchanged."""
    ...

class FanslyApiClientImpl(FanslyApiClient):
    """New fansly-api.com implementation."""
    def __init__(self, config: FanslyConfig):
        self.client = httpx.Client(base_url="https://api.fansly-api.com/v1")
        self.client.headers["Authorization"] = f"Bearer {config.api_key}"
    ...
```

## Testing Strategy

| Test | What it covers |
|------|---------------|
| `test_abc_cannot_instantiate` | ABC cannot be instantiated directly |
| `test_both_clients_implement_all_methods` | Both clients pass MRO check |
| `test_apifansly_send_message` | Existing behavior preserved |
| `test_fanslyapi_constructs_with_bearer` | New client sets Bearer token |
| `test_fanslyapi_get_all_chats` | Mocked API response parsed correctly |
| `test_fanslyapi_send_ppv` | PPV message format matches fansly-api.com |
| `test_factory_returns_apifansly` | `FANSLY_PROVIDER=apifansly` |
| `test_factory_returns_fanslyapi` | `FANSLY_PROVIDER=fanslyapi` |
| `test_bot_works_with_either_client` | Bot accepts any FanslyApiClient subclass |

## Boundaries

- **Always do:** Bot code references only the ABC — never concrete classes
- **Always do:** TDD — write failing test before new client code
- **Ask first:** Changing the bot's internal message processing logic
- **Never do:** Hardcoding provider-specific logic in bot.py

## Success Criteria

- [ ] Bot runs with fansly-api.com key and credits
- [ ] Doesn't even need FANSLY_ACCOUNT_ID (fansly-api.com handles auth differently)
- [ ] Adapter pattern proven — swap back to apifansly with one env var change
- [ ] All 14 existing tests + new tests pass
- [ ] Webhook endpoint ready for fansly-api.com events

## Open Questions

- [ ] What's the exact base URL for fansly-api.com? (Need user to share key first)
- [ ] Does fansly-api.com use `account_id` like apifansly, or handle it differently?
- [ ] What credit cost per API call? (30K credits/mo on Basic — need to calculate)
- [ ] Webhook: single shared secret or per-account?