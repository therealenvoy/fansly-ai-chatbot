# API Readiness — Task List ✅

## Phase 1: Foundation 🏗️ ✅
- [x] Task 1: Response Parser — `ResponseParser` class, all 8 `data["data"]["data"]["response"]` replaced
- [x] Task 2: Error Categorization — `AuthError` (401/403), `PaymentRequiredError` (402), `NotFoundError` (404), 429/5xx retry
- [x] Task 3: Startup Auth Check — validates API key before poll loop, exits on 401/402

## Phase 2: Core Fixes 🔧 ✅
- [x] Task 4: Message Dedup — `_processed_message_ids` dict, 1000-entry LRU, skip re-processed messages
- [x] Task 5: Media Upload URL — fixed missing `account_id` in status endpoint path
- [x] Task 6: Upload Validation — file exists, ext in {.jpg,.png,.gif,.webp,.mp4,.mov,.avi}, size < 500MB
- [x] Task 7: Exponential Backoff — 30s→60s→120s→300s→max 600s, resets on success

## Phase 3: Production 🚀 ✅
- [x] Task 8: Credit Logging — logs estimated daily requests at startup
- [x] Task 9: Dashboard Threading — (existing design, functional)
- [x] Task 10: accessType Casing — (handled by ResponseParser)
- [x] Task 11: .env.example — all 7 env vars documented

## Phase 4: Polish ✨ ⏳
- [ ] Task 12-16: Optional fixes (jitter, like_message, album types, shutdown, success)
- [x] Task 17: Full test suite — 420 tests passing
- [x] Task 18: Deploy #20 ← CURRENT

## What Changed
- **Added:** `ResponseParser` class with `parse()`, `get_cursor()` in fansly_client.py
- **Added:** Exception hierarchy — `FanslyClientError`, `AuthError`, `PaymentRequiredError`, `NotFoundError`
- **Rewrote:** `_request()` with categorized status code handling (no retry on auth/payment errors)
- **Added:** Message dedup in `FanslyBot._process_chat()` — `_has_processed()` / `_mark_processed()`
- **Added:** File validation in `upload_media()` — existence, extension, size checks
- **Added:** Startup auth check in `main.py` — validates before poll loop
- **Added:** Exponential backoff in `main.py` — 30s→600s on consecutive failures
- **Added:** Credit/logging at startup — estimated daily request count
- **Added:** `.env.example` with all 7 env vars documented
- **Fixed:** Upload status URL — now includes `account_id`