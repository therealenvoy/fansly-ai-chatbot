# Implementation Plan: API Readiness & Production Hardening

## Overview

18 tasks across 4 phases. Dependency chain: Foundation (response parser + error handling) → Message Dedup → Production features → Polish. Each phase leaves the bot in a working state.

Dependency graph:
```
Phase 1: Foundation
  Task 1 (ResponseParser) ──→ Task 2 (ErrorCategorization) ──→ Task 3 (StartupAuth)
                                │
Phase 2: Core Fixes             │
  Task 4 (MessageDedup) ←───────┘
  Task 5 (UploadURL) ──→ Task 6 (UploadValidation)
  Task 7 (Backoff)
                                │
Phase 3: Production             │
  Task 8 (CreditLogging) ←──────┘
  Task 9 (DashboardThreading)
  Task 10 (accessType)
  Task 11 (.env.example)
                                │
Phase 4: Remaining              │
  Task 12 (Jitter)
  Task 13 (like_message fix)
  Task 14 (get_album_media fix)
  Task 15 (Shutdown race)
  Task 16 (send_message fix)

Deploy:
  Task 17 (Full suite)
  Task 18 (Deploy #20)
```

## Task List

### Phase 1: Foundation (3 tasks, parallelizable)

#### Task 1: Robust Response Parser (C3 fix)
**Description:** Replace 8 fragile `data["data"]["data"]["response"]` patterns with a single validation helper.
**Acceptance:**
- `ResponseParser.parse(data)` returns typed objects for chats, messages, earnings, albums, media
- Missing/wrong keys → structured error, not KeyError
- All 8 consumer methods use the parser
**Files:** `src/fansly_client.py`, `tests/test_fansly_client.py`
**Scope:** Medium
**Dependencies:** None

#### Task 2: Error Categorization (C2, R1 fix)
**Description:** Categorize HTTP errors in `_request()`: 401/403 → PermissionError (shutdown), 402 → PaymentRequiredError (shutdown), 404 → NotFoundError (log + skip), 429 → retry (existing), 5xx → retry (existing).
**Acceptance:**
- 401/403 raises PermissionError → main.py stops polling
- 402 raises PaymentRequiredError → main.py stops polling
- 404 raises NotFoundError → caller handles gracefully
- 429 rate limits properly
- Unit tests for each status code
**Files:** `src/fansly_client.py`, `tests/test_fansly_client.py`
**Scope:** Medium
**Dependencies:** None (can parallelize with Task 1)

#### Task 3: Startup Auth Check (C5 fix)
**Description:** Validate API credentials at startup before entering the polling loop.
**Acceptance:**
- On start, bot makes 1 API call (e.g., list_chats with limit=1)
- If 401/402/403 → logs clear error + exits immediately
- If success → starts normal polling
- Does NOT burn credits in an error loop
**Files:** `src/main.py`
**Scope:** Small
**Dependencies:** Task 2 (needs error categorization)

### ✅ Checkpoint: Phase 1
- [ ] ResponseParser parses all 8 endpoint shapes
- [ ] HTTP errors categorized with correct exceptions
- [ ] Auth check exits immediately on bad credentials
- [ ] All existing 458 tests pass

### Phase 2: Core Fixes (4 tasks, sequential after Phase 1)

#### Task 4: Message Deduplication (C1 fix)
**Description:** Track processed message_ids per fan to prevent re-replying to the same message.
**Acceptance:**
- `self._processed_messages: set[str]` tracks processed message_ids
- `_has_processed(fan_id, msg_id) → bool`
- `_mark_processed(fan_id, msg_id)` stores it
- On bot restart, `_processed_messages` resets (intentional — can't persist in-memory)
- After 1000 entries, oldest entries are evicted (LRU)
- Same fan message never triggers reply twice
**Files:** `src/bot.py`, `tests/test_bot.py`
**Scope:** Medium
**Dependencies:** None (independent of Phase 1)

#### Task 5: Fix Media Upload URL (C4 fix)
**Description:** Add missing account_id to upload status URL.
**Acceptance:**
- Status URL: `/{account_id}/media/upload/{job_id}/status` instead of `/media/upload/{job_id}/status`
- Test verifies URL construction
**Files:** `src/fansly_client.py`, `tests/test_fansly_client.py`
**Scope:** XS
**Dependencies:** None

#### Task 6: Upload File Validation (R3 fix)
**Description:** Add file existence, size, and type validation before upload.
**Acceptance:**
- Non-existent file → clean error, not FileNotFoundError
- Files > 500MB → rejected
- Non-media extensions (.exe, .zip, .pdf) → rejected
- Allowed: .jpg, .jpeg, .png, .gif, .webp, .mp4, .mov, .avi
**Files:** `src/fansly_client.py`, `tests/test_fansly_client.py`
**Scope:** Small
**Dependencies:** None

#### Task 7: Exponential Backoff (R4 fix)
**Description:** Implement exponential backoff on consecutive API failures.
**Acceptance:**
- Successive failures: 30s → 60s → 120s → 300s → max 600s
- On success: reset to base interval
- Configurable base interval (default 30s)
- Logs current backoff level
**Files:** `src/main.py`, `tests/test_main.py`
**Scope:** Small
**Dependencies:** None (but integrates with main.py loop)

### ✅ Checkpoint: Phase 2
- [ ] Same message never triggers two replies
- [ ] Media upload URL correct
- [ ] Upload validates file before sending
- [ ] Backoff prevents hammering on outages
- [ ] All tests pass

### Phase 3: Production Hardening (4 tasks)

#### Task 8: Credit Awareness Logging (R2 fix)
**Description:** Log estimated daily credit burn at startup. Track approximate usage.
**Acceptance:**
- Startup logs: "Estimated credit usage: ~2,880/day at current poll interval"
- Console visible in production logs
- Warning if projected daily usage > 80% of plan
**Files:** `src/main.py`
**Scope:** XS
**Dependencies:** None

#### Task 9: Dashboard Threading (R5 fix)
**Description:** Replace blocking `handle_request()` with proper thread-served HTTP server.
**Acceptance:**
- Dashboard uses `ThreadingHTTPServer` or `serve_forever()` in daemon thread
- Multiple concurrent requests don't block
- Dashboard shuts down cleanly
**Files:** `src/web/dashboard.py`
**Scope:** Medium
**Dependencies:** None

#### Task 10: accessType Casing (R7 fix)
**Description:** Send both `access_type` and `accessType` in PPV payload to handle API variant.
**Acceptance:**
- PPV message body includes both `"access_type": "price"` and `"accessType": "price"`
- Existing tests pass without change
**Files:** `src/fansly_client.py`
**Scope:** XS
**Dependencies:** None

#### Task 11: .env.example (R8 fix)
**Description:** Create documented .env.example with all environment variables.
**Acceptance:**
- Lists: FANSLY_API_KEY, FANSLY_ACCOUNT_ID, CREATOR_ID, POLL_INTERVAL, DATABASE_URL, PORT, DEEPSEEK_API_KEY
- Each variable has description, default, and whether required
**Files:** `.env.example`
**Scope:** XS
**Dependencies:** None

### ✅ Checkpoint: Phase 3
- [ ] Credit usage logged at startup
- [ ] Dashboard handles concurrent requests
- [ ] PPV messages include both casings
- [ ] .env.example documents all vars
- [ ] All tests pass

### Phase 4: Polish + Deploy (5 tasks)

#### Task 12: Retry Jitter (O1 fix)
**Acceptance:** All retry sleeps include `random.uniform(0.5, 1.5)` multiplier.

#### Task 13: like_message response fix (O2 fix)
**Acceptance:** Uses same response parser as other methods.

#### Task 14: get_album_media type fix (O3 fix)
**Acceptance:** Normalizes response shape explicitly.

#### Task 15: Shutdown race fix (O4 fix)
**Acceptance:** Joins server thread before closing httpx client.

#### Task 16: send_message success check (O5 fix)
**Acceptance:** Checks response body for error status.

#### Task 17: Full test suite
**Acceptance:** `python3 -m pytest tests/ -q` → all pass.

#### Task 18: Deploy #20
**Acceptance:** Health endpoint responds, logs show no errors.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Response parser wrong shape for real API | High | Verified against docs.apifansly.com, but true test requires real API call |
| Message dedup eviction too aggressive | Low | 1000 entries is safe for 500 active chats × 2 messages each |
| Upload size limit wrong for video content | Medium | Videos can be large; 500MB is conservative, adjustable via constant |

## Open Questions

- What's the exact response shape of the real API? Current code expects `data["data"]["data"]["response"]` — verify this against a real API key before deploying