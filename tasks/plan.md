# Bot On/Off Toggle — Implementation Plan

> **For Hermes:** Use writing-plans + incremental-implementation + test-driven-development skills to execute this plan task-by-task.

**Goal:** Add a one-click on/off toggle button to the dashboard sidebar that instantly disables/enables the Fansly bot, persisted across restarts.

**Architecture:** SettingsStore (key-value DB table) → FanslyBot.enabled flag (guards poll_and_process()) → Dashboard API (toggle + status endpoints) → UI pill button. Data flows: DB → bot → API → UI.

**Tech Stack:** Python 3.11, SQLAlchemy Core (existing pattern), inline JS, pytest

---

## Dependency Graph

```
SettingsStore (foundation)
  ├── FanslyBot.enabled flag + guard
  │     ├── Dashboard API: POST /api/bot/toggle + GET /api/bot/status
  │     │     └── Dashboard UI: pill button in sidebar
  │     └── main.py: init from DB → pass to bot
  └── test_settings.py (TDD)
        └── test_bot.py (TDD)
```

---

## Task 1: Create SettingsStore

**Objective:** Key-value settings table with `.get(key, default)` and `.set(key, value)`.

**Files:**
- Create: `src/settings/__init__.py` (empty)
- Create: `src/settings/store.py` (SettingsStore class)
- Create: `tests/test_settings.py` (TDD tests)

**Step 1: Write failing test**
```python
"""Tests for SettingsStore — key-value persistence."""
import pytest
from src.settings.store import SettingsStore, BOT_SETTINGS_TABLE

@pytest.fixture
def store():
    """In-memory SQLite SettingsStore for testing."""
    s = SettingsStore("sqlite:///:memory:")
    s.create_table()
    return s

def test_get_default_on_empty_key():
    s = store()
    assert s.get("bot_enabled", True) == True

def test_set_and_get_string():
    s = store()
    s.set("bot_enabled", "false")
    assert s.get("bot_enabled") == "false"

def test_set_and_get_boolean():
    s = store()
    s.set("bot_enabled", False)
    assert s.get("bot_enabled", True) == "false"

def test_set_overwrites():
    s = store()
    s.set("key", "v1")
    s.set("key", "v2")
    assert s.get("key") == "v2"

def test_get_nonexistent_returns_default():
    s = store()
    assert s.get("nah", 42) == 42

def test_persists_across_instances():
    s1 = SettingsStore("sqlite:///tmp/test_settings.db")
    s1.create_table()
    s1.set("bot_enabled", "false")
    s2 = SettingsStore("sqlite:///tmp/test_settings.db")
    s2.create_table()
    assert s2.get("bot_enabled") == "false"
```

**Step 2: Run test to verify failure**

Run: `pytest tests/test_settings.py -v`
Expected: FAIL — ModuleNotFoundError / ImportError

**Step 3: Implement SettingsStore**

```python
"""SettingsStore — key-value persistence for bot settings."""
import json
from sqlalchemy import create_engine, MetaData, Table, Column, String, Text

BOT_SETTINGS_TABLE = Table(
    "bot_settings",
    MetaData(),
    Column("key", String, primary_key=True),
    Column("value", Text, nullable=True),
)


class SettingsStore:
    """Simple key-value store for bot settings, persisted to SQLite/Postgres."""

    def __init__(self, db_url: str):
        self.engine = create_engine(db_url)

    def create_table(self):
        BOT_SETTINGS_TABLE.create(self.engine, checkfirst=True)

    def get(self, key: str, default=None) -> str:
        from sqlalchemy import select
        with self.engine.connect() as conn:
            result = conn.execute(
                select(BOT_SETTINGS_TABLE.c.value).where(
                    BOT_SETTINGS_TABLE.c.key == key
                )
            ).scalar_one_or_none()
        return result if result is not None else default

    def set(self, key: str, value: str):
        with self.engine.begin() as conn:
            conn.execute(
                BOT_SETTINGS_TABLE.update()
                .where(BOT_SETTINGS_TABLE.c.key == key)
                .values(value=value)
            )
            if conn.execute(
                select(BOT_SETTINGS_TABLE.c.key).where(
                    BOT_SETTINGS_TABLE.c.key == key
                )
            ).scalar_one_or_none() is None:
                conn.execute(
                    BOT_SETTINGS_TABLE.insert().values(key=key, value=value)
                )
```

**Step 4: Run test to verify pass**

Run: `pytest tests/test_settings.py -v`
Expected: ALL PASS (6/6)

**Step 5: Commit**

```bash
git add src/settings/ tests/test_settings.py
git commit -m "feat: add SettingsStore key-value persistence"
```

---

## Task 2: Add enabled flag to FanslyBot

**Objective:** `self.enabled` flag, guard in `poll_and_process()`, toggle method.

**Files:**
- Modify: `src/bot.py` (add flag + guard + toggle method)
- Create: `tests/test_bot.py` (TDD tests for toggle)

**Step 1: Write failing tests**
```python
"""Tests for FanslyBot on/off toggle."""
import pytest
from unittest.mock import MagicMock, patch
from src.bot import FanslyBot
from src.notes.repository import FanNoteRepository
from src.persona.loader import PersonaLoader
from src.fansly_client import FanslyClient, FanslyConfig, ChatInfo

@pytest.fixture
def bot():
    client = MagicMock(spec=FanslyClient)
    client.config = FanslyConfig(api_key="test", account_id="test")
    # Mock get_all_chats to return empty list
    client.get_all_chats.return_value = []
    pl = MagicMock(spec=PersonaLoader)
    pl.load.return_value = MagicMock()
    pl.load.return_value.forbidden_phrases = []
    pl.load.return_value.pet_names = ["babe"]
    pl.load.return_value.common_typos = {}
    nr = FanNoteRepository("sqlite:///:memory:")
    nr.create_table()
    b = FanslyBot(client=client, persona_loader=pl, note_repo=nr)
    b.enabled = True  # reset after init
    return b

def test_bot_enabled_by_default():
    """Bot should be enabled on init."""
    b = bot()
    # Don't override — test the default
    b2 = FanslyBot(
        client=b.client, persona_loader=b.persona_loader, note_repo=b.note_repo
    )
    assert b2.enabled == True

def test_poll_skips_when_disabled():
    """poll_and_process should return early when bot is disabled."""
    b = bot()
    b.enabled = False
    b.poll_and_process()
    b.client.get_all_chats.assert_not_called()

def test_poll_calls_api_when_enabled():
    """poll_and_process should call API when bot is enabled."""
    b = bot()
    b.enabled = True
    b.poll_and_process()
    b.client.get_all_chats.assert_called_once()

def test_toggle_off():
    """toggle() should set enabled=False when called with force=False."""
    b = bot()
    b.enabled = True
    result = b.toggle(force=False)
    assert b.enabled == False
    assert result == False

def test_toggle_on():
    """toggle() should set enabled=True when currently disabled."""
    b = bot()
    b.enabled = False
    result = b.toggle(force=None)
    assert b.enabled == True
    assert result == True
```

**Step 2: Run test to verify failure**

Run: `pytest tests/test_bot.py -v`
Expected: FAIL — missing `enabled` attribute / `toggle` method

**Step 3: Add flag + guard + toggle to bot.py**

In `FanslyBot.__init__`, add:
```python
self.enabled = True  # Bot starts enabled; main.py overrides from DB
```

Add to `poll_and_process()` BEFORE the first line of logic:
```python
if not self.enabled:
    logger.debug("Bot disabled — skipping poll cycle")
    return
```

Add method:
```python
def toggle(self, force: Optional[bool] = None) -> bool:
    """Toggle bot on/off. Returns new enabled state.
    If force is True/False, set to that state; otherwise flip."""
    if force is not None:
        self.enabled = bool(force)
    else:
        self.enabled = not self.enabled
    logger.info(f"Bot {'enabled' if self.enabled else 'disabled'}")
    return self.enabled
```

**Step 4: Run test to verify pass**

Run: `pytest tests/test_bot.py -v`
Expected: ALL PASS (5/5)

**Step 5: Commit**

```bash
git add src/bot.py tests/test_bot.py
git commit -m "feat: add bot enabled flag + toggle method + poll guard"
```

---

## Task 3: Init flag from SettingsStore in main.py

**Objective:** On startup, read `bot_enabled` from DB and pass to bot.

**Files:**
- Modify: `src/main.py` (create SettingsStore, read flag, pass to bot)

**Step 1: Write failing test**
```python
def test_bot_reads_enabled_from_db():
    """Bot should initialize enabled flag from SettingsStore."""
    # ... (implemented in test_bot.py)
```

**Step 2: Modify main.py**

After `note_repo.create_table()`, add:
```python
from .settings.store import SettingsStore
settings_store = SettingsStore(db_url=DB_URL)
settings_store.create_table()
```

After `bot = FanslyBot(...)`, add:
```python
# Initialize enabled flag from persistent settings
bot_enabled_str = settings_store.get("bot_enabled", "true")
bot.enabled = bot_enabled_str.lower() == "true"
logger.info(f"Bot enabled state from DB: {bot.enabled}")
```

**Step 3: Verify manually**

Run: `python -m src.main` (requires API key)
Expected: Logs "Bot enabled state from DB: True"

---

## Task 4: Dashboard API endpoints

**Objective:** `GET /api/bot/status` and `POST /api/bot/toggle`.

**Files:**
- Modify: `src/web/dashboard.py` (add routes + handlers)

**Step 1: Write failing tests in test_bot.py**
```python
def test_api_bot_status_endpoint():
    """GET /api/bot/status should return enabled state."""
    # ... (requires HTTP test setup — skip for now)
```

**Step 2: Add to dashboard.py**

In `do_GET`, add:
```python
if p == "/api/bot/status":
    return self.j({"enabled": self.bot.enabled if self.bot else False})
```

In `do_POST`, add:
```python
if p == "/api/bot/toggle":
    return self._bot_toggle(b)
```

Add handler:
```python
def _bot_toggle(self, body: str):
    if not self.bot:
        return self.j({"error": "bot not initialized"}, 503)
    try:
        data = json.loads(body) if body else {}
        force = data.get("enabled") if "enabled" in data else None
        new_state = self.bot.toggle(force=force)
        # Persist
        from ..settings.store import SettingsStore
        store = SettingsStore(db_url=self.bot.note_repo.engine.url.render_as_string(
            hide_password=False
        ) if hasattr(self.bot.note_repo.engine.url, 'render_as_string') else str(self.bot.note_repo.engine.url))
        store.create_table()
        store.set("bot_enabled", str(new_state).lower())
        return self.j({"enabled": new_state})
    except Exception as e:
        return self.j({"error": str(e)}, 500)
```

Update `/health` to include bot state:
```python
if p == "/health":
    return self.j({
        "status": "ok",
        "service": "fansly-bot",
        "creator": self.bot.creator_id if self.bot else None,
        "bot_enabled": self.bot.enabled if self.bot else False,
    })
```

---

## Task 5: Dashboard UI — toggle pill button in sidebar

**Objective:** The green dot in the sidebar becomes a clickable toggle pill. Shows "ON" (green) or "OFF" (red). Clicking toggles instantly.

**Files:**
- Modify: `src/web/dashboard.py` (HTML + JS in DASHBOARD_HTML)

**Step 1: Replace the green dot HTML**

In the sidebar logo section, replace:
```html
<div class="logo"><span class="dot" id="dot"></span><span>Sunny Charm</span></div>
```

With:
```html
<div class="logo">
  <span class="toggle-pill" id="bot-toggle" onclick="toggleBot()">
    <span class="toggle-dot" id="dot"></span>
    <span id="toggle-label">ON</span>
  </span>
  <span>Sunny Charm</span>
</div>
```

**Step 2: Add CSS**

```css
.toggle-pill{display:inline-flex;align-items:center;gap:5px;padding:3px 10px 3px 6px;border-radius:9999px;cursor:pointer;transition:all .15s;border:1px solid var(--bsub);background:var(--surf);font-size:10px;font-weight:600;letter-spacing:.3px;user-select:none}
.toggle-pill:hover{background:var(--hover)}
.toggle-pill .dot{width:6px;height:6px;border-radius:50%;background:var(--green);box-shadow:0 0 5px rgba(39,166,68,0.3)}
.toggle-pill .dot.off{background:#f87171;box-shadow:0 0 5px rgba(248,113,113,0.3)}
```

**Step 3: Add JS functions**

```javascript
async function loadBotStatus(){
  var r=await fetch('/api/bot/status');
  var d=await r.json();
  updateToggleUI(d.enabled);
}
function updateToggleUI(enabled){
  var dot=document.getElementById('dot');
  var label=document.getElementById('toggle-label');
  dot.className='dot'+(enabled?'':' off');
  label.textContent=enabled?'ON':'OFF';
  label.style.color=enabled?'var(--green)':'#f87171';
}
async function toggleBot(){
  var r=await fetch('/api/bot/toggle',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  var d=await r.json();
  updateToggleUI(d.enabled);
}
```

**Step 4: Call on load and on interval**

Replace the interval health check at the bottom:
```javascript
loadBotStatus();
setInterval(function(){loadBotStatus()},15000);
loadFunnel();
```

---

## Task 6: Log transition on toggle (not on every poll)

**Objective:** Log once when bot transitions from enabled→disabled or disabled→enabled, not every poll cycle.

**Files:**
- Modify: `src/bot.py` (toggle method already logs)

The `toggle()` method already logs with `logger.info(f"Bot {'enabled' if self.enabled else 'disabled'}"`). The guard in `poll_and_process()` uses `logger.debug` which is silent by default. ✓

---

## Verification

After all tasks:

- [ ] `pytest tests/ -q` — all tests pass (including existing 244)
- [ ] Toggle button visible in sidebar
- [ ] Clicking toggle instantly changes state
- [ ] Restarting the container preserves toggle state
- [ ] `/health` returns `bot_enabled: true/false`
- [ ] When disabled, no API calls are made (check logs for "skipping poll cycle")