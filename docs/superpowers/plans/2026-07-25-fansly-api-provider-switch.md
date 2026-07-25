# Fansly API Provider Switch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second Fansly API client (OnlyFansAPI's Fansly product, `app.onlyfansapi.com`) behind the existing client's interface, switchable via env var, with idle-adaptive polling so the bot doesn't burn through credits when nothing's happening.

**Architecture:** Extract an abstract `FanslyApiClient` interface from the current `FanslyClient` (renamed `ApifanslyClient`). Add `FanslyApiClientImpl` implementing the same interface against the new provider. A factory function picks the concrete class from `FANSLY_PROVIDER`. `bot.py` and `main.py` are updated to depend only on the interface, plus `bot.py` gains an unread-count pre-filter and `main.py` gains idle-adaptive backoff.

**Tech Stack:** Python 3.11+, httpx, `abc.ABC`, pytest (TDD, mocked HTTP — no real API credits spent by tests).

## Global Constraints

- Base URL for the new provider: `https://app.onlyfansapi.com` (verified against live docs, not guessed)
- Auth header for the new provider: `Authorization: Bearer <token>` (not `x-api-key`)
- New provider PPV pricing unit: millidollars, `1000 = $1.00` (int), vs. apifansly's dollar float
- New provider has no vault/album endpoints and no earnings endpoints — `FanslyApiClientImpl` raises `NotImplementedError` for these, never silently returns empty data
- No webhook work in this plan — no Fansly-scoped webhook events exist on this provider yet
- `bot.py`'s public behavior (aside from the unread filter and the `poll_and_process` return value) does not change
- Every existing test that doesn't directly reference `FanslyClient` by name must keep passing unmodified

---

### Task 1: Extract `FanslyApiClient` ABC, rename `FanslyClient` → `ApifanslyClient`

**Files:**
- Modify: `src/fansly_client.py`
- Modify: `tests/test_fansly_client.py`
- Modify: `tests/test_bot_dedup.py`
- Modify: `tests/test_fansly_upload.py`

**Interfaces:**
- Produces: `FanslyApiClient(ABC)` with abstract methods `get_all_chats(filter_type="all") -> list[ChatInfo]`, `list_messages(chat_id, limit=10) -> tuple[list[MessageInfo], Optional[str]]`, `send_message(chat_id, content, media_ids=None, access_type=None, price=None) -> SentMessage`, `send_ppv(chat_id, content, media_id, price, preview_id=None) -> SentMessage`, `like_message(chat_id, message_id) -> bool`, `upload_media(file_path) -> str`, `list_albums() -> list[dict]`, `get_album_media(album_id, cursor=None) -> tuple[list[dict], Optional[str]]`, `verify_auth() -> bool`, `close()`, and abstract property `account_id -> str`.
- Produces: `ApifanslyClient(FanslyApiClient)` — today's `FanslyClient` body, renamed, `account_id` property returns `self.config.account_id`, `verify_auth()` wraps the existing startup-check call.

- [ ] **Step 1: Write the failing test for the ABC contract**

Add to `tests/test_fansly_client.py` (after the existing imports, which will also need updating — see Step 5):

```python
class TestFanslyApiClientABC:
    """The abstract interface cannot be instantiated; ApifanslyClient implements it fully."""

    def test_abc_cannot_be_instantiated(self):
        from src.fansly_client import FanslyApiClient
        with pytest.raises(TypeError):
            FanslyApiClient()

    def test_apifansly_client_is_a_fansly_api_client(self):
        from src.fansly_client import ApifanslyClient, FanslyApiClient, FanslyConfig
        config = FanslyConfig(api_key="k", account_id="a")
        client = ApifanslyClient(config)
        assert isinstance(client, FanslyApiClient)

    def test_apifansly_account_id_property(self):
        from src.fansly_client import ApifanslyClient, FanslyConfig
        config = FanslyConfig(api_key="k", account_id="acct_789")
        client = ApifanslyClient(config)
        assert client.account_id == "acct_789"

    def test_apifansly_verify_auth_success(self):
        from src.fansly_client import ApifanslyClient, FanslyConfig
        config = FanslyConfig(api_key="k", account_id="a")
        client = ApifanslyClient(config)
        client._request = MagicMock(return_value={"statusCode": 200, "data": {"data": {"response": []}}})
        assert client.verify_auth() is True
        client._request.assert_called_once_with("GET", "/a/chats", params={"limit": 1})

    def test_apifansly_verify_auth_raises_on_auth_error(self):
        from src.fansly_client import ApifanslyClient, FanslyConfig, AuthError
        config = FanslyConfig(api_key="k", account_id="a")
        client = ApifanslyClient(config)
        client._request = MagicMock(side_effect=AuthError("bad key"))
        with pytest.raises(AuthError):
            client.verify_auth()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_fansly_client.py::TestFanslyApiClientABC -v`
Expected: FAIL — `FanslyApiClient` and `ApifanslyClient` don't exist yet (`ImportError`).

- [ ] **Step 3: Implement the ABC and rename in `src/fansly_client.py`**

Add near the top of `src/fansly_client.py`, after the existing imports (add `from abc import ABC, abstractmethod`):

```python
from abc import ABC, abstractmethod


class FanslyApiClient(ABC):
    """Abstract interface for a Fansly API provider. Bot code depends only on this."""

    @property
    @abstractmethod
    def account_id(self) -> str: ...

    @abstractmethod
    def verify_auth(self) -> bool:
        """Verify credentials are valid. Raises AuthError/PaymentRequiredError on failure."""
        ...

    @abstractmethod
    def get_all_chats(self, filter_type: str = "all") -> list["ChatInfo"]: ...

    @abstractmethod
    def list_messages(
        self, chat_id: str, limit: int = 10, cursor: Optional[str] = None
    ) -> tuple[list["MessageInfo"], Optional[str]]: ...

    @abstractmethod
    def send_message(
        self,
        chat_id: str,
        content: str,
        media_ids: Optional[list[dict]] = None,
        access_type: Optional[list[str]] = None,
        price: Optional[float] = None,
    ) -> "SentMessage": ...

    @abstractmethod
    def send_ppv(
        self,
        chat_id: str,
        content: str,
        media_id: str,
        price: float,
        preview_id: Optional[str] = None,
    ) -> "SentMessage": ...

    @abstractmethod
    def like_message(self, chat_id: str, message_id: str) -> bool: ...

    @abstractmethod
    def upload_media(self, file_path: str) -> str: ...

    @abstractmethod
    def list_albums(self) -> list[dict]: ...

    @abstractmethod
    def get_album_media(
        self, album_id: str, cursor: Optional[str] = None
    ) -> tuple[list[dict], Optional[str]]: ...

    @abstractmethod
    def close(self): ...
```

Then:
1. Rename `class FanslyClient:` to `class ApifanslyClient(FanslyApiClient):`
2. Add this property and method to `ApifanslyClient`, right after `__init__`:

```python
    @property
    def account_id(self) -> str:
        return self.config.account_id

    def verify_auth(self) -> bool:
        """Minimal API call to confirm credentials are valid before polling starts."""
        self._request("GET", f"/{self.config.account_id}/chats", params={"limit": 1})
        return True
```

3. Add `MagicMock` import used by the new tests: in `tests/test_fansly_client.py`, `from unittest.mock import MagicMock` already exists at the top — no change needed there.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_fansly_client.py::TestFanslyApiClientABC -v`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Update existing test imports for the rename**

In `tests/test_fansly_client.py`, change the import line:

```python
from src.fansly_client import (
    ApifanslyClient as FanslyClient, FanslyConfig, ResponseParser,
    FanslyClientError, PaymentRequiredError, NotFoundError, AuthError,
    ChatInfo, MessageInfo, SentMessage,
)
```

(Using `ApifanslyClient as FanslyClient` keeps every existing test body in this file — which references the local name `FanslyClient` — working unchanged.)

In `tests/test_bot_dedup.py`, change:

```python
from src.fansly_client import FanslyClient, FanslyConfig, ChatInfo, MessageInfo
```

to:

```python
from src.fansly_client import ApifanslyClient as FanslyClient, FanslyConfig, ChatInfo, MessageInfo
```

In `tests/test_fansly_upload.py`, change:

```python
    FanslyClient, FanslyConfig,
```

(inside its import statement) to:

```python
    ApifanslyClient as FanslyClient, FanslyConfig,
```

- [ ] **Step 6: Run the full existing client/bot test suite to verify nothing broke**

Run: `pytest tests/test_fansly_client.py tests/test_bot_dedup.py tests/test_fansly_upload.py -v`
Expected: PASS — all tests, old and new.

- [ ] **Step 7: Commit**

```bash
git add src/fansly_client.py tests/test_fansly_client.py tests/test_bot_dedup.py tests/test_fansly_upload.py
git commit -m "refactor: extract FanslyApiClient ABC, rename FanslyClient to ApifanslyClient"
```

---

### Task 2: Implement `FanslyApiClientImpl` for the new provider

**Files:**
- Create: `src/fansly_api_client.py`
- Create: `tests/test_fansly_api_client.py`

**Interfaces:**
- Consumes: `FanslyApiClient` (ABC), `ChatInfo`, `MessageInfo`, `SentMessage`, `AuthError`, `PaymentRequiredError`, `NotFoundError` — all from `src.fansly_client` (Task 1).
- Produces: `FanslyApiClientImpl(FanslyApiClient)`, constructed as `FanslyApiClientImpl(api_key: str, timeout: float = 30.0)`. `account_id` resolves lazily on first access (via `verify_auth()` or first API call) and is cached — construction does no network I/O, matching `ApifanslyClient`'s pattern.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fansly_api_client.py`:

```python
"""Tests for FanslyApiClientImpl — the app.onlyfansapi.com Fansly provider.

Every mocked response body below is the REAL shape captured from
docs.onlyfansapi.com/api-reference/fansly during the design session for
this feature (2026-07-25), not invented data.
"""
import pytest
import httpx
from unittest.mock import MagicMock

from src.fansly_client import FanslyApiClient, AuthError, PaymentRequiredError
from src.fansly_api_client import FanslyApiClientImpl


def _resp(json_body: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_body
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(spec=httpx.Request), response=resp
        )
    return resp


LIST_ACCOUNTS_BODY = [
    {
        "id": "fansly_acct_123",
        "display_name": "My Fansly",
        "fansly_id": "111222333",
        "fansly_username": "tester",
        "is_authenticated": True,
        "authentication_progress": "authenticated",
    }
]

LIST_CHATS_BODY = {
    "data": {
        "data": [
            {
                "groupId": "200000000000000001",
                "partnerAccountId": "300000000000000001",
                "partnerUsername": "partner",
                "unreadCount": 1,
                "lastMessageId": "400000000000000001",
                "subscriptionTierId": None,
            }
        ],
        "aggregationData": {
            "accounts": [
                {
                    "id": "300000000000000001",
                    "username": "partner",
                    "displayName": "Partner",
                    "avatar": {"locations": [{"location": "https://cdn3.fansly.com/x.jpeg"}]},
                }
            ]
        },
        "hasMore": False,
    },
    "_pagination": {"next_page": None},
}

LIST_MESSAGES_BODY = {
    "data": {
        "messages": [
            {
                "id": "400000000000000001",
                "content": "hey",
                "groupId": "200000000000000001",
                "senderId": "300000000000000001",
                "createdAt": 1700000000,
                "attachments": [],
                "totalTipAmount": 0,
            }
        ],
        "hasMore": False,
    }
}

SEND_MESSAGE_BODY = {
    "data": {
        "type": 1,
        "attachments": [],
        "content": "Hey there!",
        "groupId": "200000000000000001",
        "senderId": "100000000000000001",
        "id": "400000000000000010",
        "createdAt": 1700000000.123,
    }
}

ADD_REACTION_BODY = {
    "data": {
        "accountId": "100000000000000001",
        "messageId": "300000000000000001",
        "type": 1,
        "groupId": "200000000000000001",
        "id": "500000000000000001",
    }
}

UPLOAD_MEDIA_BODY = {
    "prefixed_id": "fansly_media_01JR1234ABCD5678EFGH",
    "file_name": "photo.jpg",
    "media_id": "800000000000000010",
    "credits_used": 1,
}


class TestFanslyApiClientImplIsAFanslyApiClient:
    def test_is_instance_of_abc(self):
        client = FanslyApiClientImpl(api_key="sk_test")
        assert isinstance(client, FanslyApiClient)


class TestAccountIdResolution:
    def test_verify_auth_resolves_and_caches_account_id(self):
        client = FanslyApiClientImpl(api_key="sk_test")
        client.client.request = MagicMock(return_value=_resp(LIST_ACCOUNTS_BODY))

        assert client.verify_auth() is True
        assert client.account_id == "fansly_acct_123"
        # Cached — a second access does not re-request.
        client.client.request.assert_called_once()

    def test_verify_auth_raises_auth_error_on_401(self):
        client = FanslyApiClientImpl(api_key="bad_key")
        client.client.request = MagicMock(return_value=_resp({"error": "Unauthorized"}, 401))

        with pytest.raises(AuthError):
            client.verify_auth()

    def test_account_id_access_triggers_resolution_if_not_yet_done(self):
        client = FanslyApiClientImpl(api_key="sk_test")
        client.client.request = MagicMock(return_value=_resp(LIST_ACCOUNTS_BODY))

        assert client.account_id == "fansly_acct_123"


class TestGetAllChats:
    def test_parses_chats_from_real_response_shape(self):
        client = FanslyApiClientImpl(api_key="sk_test")
        client._account_id = "fansly_acct_123"  # pre-resolved, skip verify_auth for this test
        client.client.request = MagicMock(return_value=_resp(LIST_CHATS_BODY))

        chats = client.get_all_chats()

        assert len(chats) == 1
        assert chats[0].chat_id == "200000000000000001"
        assert chats[0].partner_account_id == "300000000000000001"
        assert chats[0].partner_display_name == "Partner"
        assert chats[0].unread_count == 1

        called_url = client.client.request.call_args[0][1]
        assert called_url == "/api/fansly/fansly_acct_123/chats"

    def test_paginates_until_has_more_is_false(self):
        """A creator with more chats than one page must not be silently truncated."""
        import copy

        page1 = copy.deepcopy(LIST_CHATS_BODY)
        page1["data"]["hasMore"] = True
        page1["data"]["data"][0]["groupId"] = "page1_chat"

        page2 = copy.deepcopy(LIST_CHATS_BODY)
        page2["data"]["hasMore"] = False
        page2["data"]["data"][0]["groupId"] = "page2_chat"

        client = FanslyApiClientImpl(api_key="sk_test")
        client._account_id = "fansly_acct_123"
        client.client.request = MagicMock(side_effect=[_resp(page1), _resp(page2)])

        chats = client.get_all_chats()

        assert [c.chat_id for c in chats] == ["page1_chat", "page2_chat"]
        assert client.client.request.call_count == 2
        first_call_params = client.client.request.call_args_list[0].kwargs["params"]
        second_call_params = client.client.request.call_args_list[1].kwargs["params"]
        assert first_call_params == {"limit": 100, "offset": 0}
        # page1's mock body contains exactly 1 chat, so offset advances by 1 (actual
        # count returned), not by the requested page size — a short page is valid.
        assert second_call_params == {"limit": 100, "offset": 1}


class TestListMessages:
    def test_parses_messages_from_real_response_shape(self):
        client = FanslyApiClientImpl(api_key="sk_test")
        client._account_id = "fansly_acct_123"
        client.client.request = MagicMock(return_value=_resp(LIST_MESSAGES_BODY))

        messages, cursor = client.list_messages("200000000000000001")

        assert len(messages) == 1
        assert messages[0].message_id == "400000000000000001"
        assert messages[0].content == "hey"
        assert messages[0].is_from_fan is True  # senderId != our account_id


class TestSendMessage:
    def test_sends_text_message(self):
        client = FanslyApiClientImpl(api_key="sk_test")
        client._account_id = "fansly_acct_123"
        client.client.request = MagicMock(return_value=_resp(SEND_MESSAGE_BODY))

        result = client.send_message("200000000000000001", "Hey there!")

        assert result.success is True
        assert result.message_id == "400000000000000010"
        sent_body = client.client.request.call_args.kwargs["json"]
        assert sent_body["text"] == "Hey there!"


class TestSendPpv:
    def test_sends_ppv_with_millidollar_price(self):
        client = FanslyApiClientImpl(api_key="sk_test")
        client._account_id = "fansly_acct_123"
        client.client.request = MagicMock(return_value=_resp(SEND_MESSAGE_BODY))

        client.send_ppv("200000000000000001", "unlock this", "fansly_media_123", price=10.0)

        sent_body = client.client.request.call_args.kwargs["json"]
        assert sent_body["mediaFiles"] == ["fansly_media_123"]
        assert sent_body["requirePurchase"] is True
        assert sent_body["price"] == 10000  # $10.00 -> 10000 millidollars

    def test_sends_ppv_with_preview(self):
        client = FanslyApiClientImpl(api_key="sk_test")
        client._account_id = "fansly_acct_123"
        client.client.request = MagicMock(return_value=_resp(SEND_MESSAGE_BODY))

        client.send_ppv(
            "200000000000000001", "unlock", "fansly_media_123",
            price=5.0, preview_id="fansly_media_preview_1",
        )

        sent_body = client.client.request.call_args.kwargs["json"]
        assert sent_body["previews"] == {"fansly_media_123": "fansly_media_preview_1"}


class TestLikeMessage:
    def test_likes_with_heart_reaction(self):
        client = FanslyApiClientImpl(api_key="sk_test")
        client._account_id = "fansly_acct_123"
        client.client.request = MagicMock(return_value=_resp(ADD_REACTION_BODY))

        result = client.like_message("200000000000000001", "300000000000000001")

        assert result is True
        sent_body = client.client.request.call_args.kwargs["json"]
        assert sent_body["type"] == 1


class TestUploadMedia:
    def test_uploads_via_file_url_and_returns_media_id(self, tmp_path):
        client = FanslyApiClientImpl(api_key="sk_test")
        client._account_id = "fansly_acct_123"
        client.client.request = MagicMock(return_value=_resp(UPLOAD_MEDIA_BODY))

        f = tmp_path / "photo.jpg"
        f.write_bytes(b"fake-image-bytes")

        media_id = client.upload_media(str(f))

        assert media_id == "fansly_media_01JR1234ABCD5678EFGH"


class TestUnsupportedEndpoints:
    def test_list_albums_raises_not_implemented(self):
        client = FanslyApiClientImpl(api_key="sk_test")
        with pytest.raises(NotImplementedError):
            client.list_albums()

    def test_get_album_media_raises_not_implemented(self):
        client = FanslyApiClientImpl(api_key="sk_test")
        with pytest.raises(NotImplementedError):
            client.get_album_media("album_1")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_fansly_api_client.py -v`
Expected: FAIL — `src.fansly_api_client` module doesn't exist yet.

- [ ] **Step 3: Implement `src/fansly_api_client.py`**

```python
"""Fansly API Client — OnlyFansAPI's Fansly product (app.onlyfansapi.com).

Base URL: https://app.onlyfansapi.com
Auth: Authorization: Bearer <token>
Docs: https://docs.onlyfansapi.com/api-reference/fansly (closed beta)

Confirmed gaps in this closed beta: no vault/album endpoints, no earnings
endpoints. Methods for those raise NotImplementedError rather than
silently returning empty data.
"""

import logging
from typing import Optional

import httpx

from .fansly_client import (
    FanslyApiClient,
    ChatInfo,
    MessageInfo,
    SentMessage,
    AuthError,
    PaymentRequiredError,
    NotFoundError,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://app.onlyfansapi.com"


class FanslyApiClientImpl(FanslyApiClient):
    """HTTP client for OnlyFansAPI's Fansly product."""

    def __init__(self, api_key: str, timeout: float = 30.0):
        self.api_key = api_key
        self.timeout = timeout
        self._account_id: Optional[str] = None
        self.client = httpx.Client(
            base_url=BASE_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    @property
    def account_id(self) -> str:
        if self._account_id is None:
            self._resolve_account_id()
        return self._account_id

    def _resolve_account_id(self):
        data = self._request("GET", "/api/fansly/accounts")
        accounts = data if isinstance(data, list) else []
        if not accounts:
            raise AuthError("No connected Fansly account found on this API key")
        self._account_id = accounts[0]["id"]

    def verify_auth(self) -> bool:
        """Resolve and cache the connected account id — also proves the key works."""
        self._resolve_account_id()
        return True

    def _request(self, method: str, path: str, **kwargs) -> dict | list:
        response = self.client.request(method, path, **kwargs)

        if response.status_code in (401, 403):
            raise AuthError(f"Authentication failed: {response.status_code} on {method} {path}")
        if response.status_code == 402:
            raise PaymentRequiredError(f"Payment required: {response.text}")
        if response.status_code == 404:
            raise NotFoundError(f"Resource not found: {path}")

        response.raise_for_status()
        return response.json()

    # ─── CHATS ───────────────────────────────────────────

    def get_all_chats(self, filter_type: str = "all") -> list[ChatInfo]:
        """Paginate through every chat page — a partial fetch would silently drop fans."""
        all_chats: list[ChatInfo] = []
        offset = 0
        page_size = 100  # API max per page — fewer round trips than the 20 default

        while True:
            data = self._request(
                "GET", f"/api/fansly/{self.account_id}/chats",
                params={"limit": page_size, "offset": offset},
            )
            inner = data.get("data", {})
            chats_raw = inner.get("data", [])

            accounts = {}
            for acc in inner.get("aggregationData", {}).get("accounts", []):
                accounts[acc["id"]] = acc

            for chat in chats_raw:
                partner_id = chat.get("partnerAccountId", "")
                acc_info = accounts.get(partner_id, {})
                avatar_url = None
                locations = acc_info.get("avatar", {}).get("locations", [])
                if locations:
                    avatar_url = locations[0].get("location")

                all_chats.append(ChatInfo(
                    chat_id=chat["groupId"],
                    partner_account_id=partner_id,
                    partner_username=chat.get("partnerUsername", acc_info.get("username", "")),
                    partner_display_name=acc_info.get("displayName", chat.get("partnerUsername", "")),
                    unread_count=chat.get("unreadCount", 0),
                    last_message_id=chat.get("lastMessageId"),
                    subscription_tier_id=chat.get("subscriptionTierId"),
                    avatar_url=avatar_url,
                ))

            if not inner.get("hasMore") or not chats_raw:
                break
            offset += len(chats_raw)

        return all_chats

    def list_messages(
        self, chat_id: str, limit: int = 10, cursor: Optional[str] = None
    ) -> tuple[list[MessageInfo], Optional[str]]:
        params = {"limit": limit}
        if cursor:
            params["before"] = cursor

        data = self._request(
            "GET", f"/api/fansly/{self.account_id}/chats/{chat_id}/messages", params=params
        )
        inner = data.get("data", {})
        messages_raw = inner.get("messages", [])

        messages = []
        for msg in messages_raw:
            is_fan = msg.get("senderId") != self.account_id
            messages.append(MessageInfo(
                message_id=msg["id"],
                content=msg.get("content", ""),
                sender_id=msg["senderId"],
                created_at=msg.get("createdAt", 0),
                is_from_fan=is_fan,
                has_attachments=bool(msg.get("attachments")),
                total_tip=msg.get("totalTipAmount", 0),
                attachments=msg.get("attachments", []),
            ))

        next_cursor = messages[-1].message_id if inner.get("hasMore") and messages else None
        return messages, next_cursor

    def send_message(
        self,
        chat_id: str,
        content: str,
        media_ids: Optional[list[dict]] = None,
        access_type: Optional[list[str]] = None,
        price: Optional[float] = None,
    ) -> SentMessage:
        body = {"text": content}
        if media_ids:
            body["mediaFiles"] = [m["mediaId"] for m in media_ids]

        data = self._request(
            "POST", f"/api/fansly/{self.account_id}/chats/{chat_id}/messages", json=body
        )
        msg = data.get("data", {})
        return SentMessage(
            message_id=msg["id"],
            content=msg.get("content", ""),
            created_at=msg.get("createdAt", 0),
            success=True,
        )

    def send_ppv(
        self,
        chat_id: str,
        content: str,
        media_id: str,
        price: float,
        preview_id: Optional[str] = None,
    ) -> SentMessage:
        body = {
            "text": content,
            "mediaFiles": [media_id],
            "requirePurchase": True,
            "price": int(round(price * 1000)),  # dollars -> millidollars
        }
        if preview_id:
            body["previews"] = {media_id: preview_id}

        data = self._request(
            "POST", f"/api/fansly/{self.account_id}/chats/{chat_id}/messages", json=body
        )
        msg = data.get("data", {})
        return SentMessage(
            message_id=msg["id"],
            content=msg.get("content", ""),
            created_at=msg.get("createdAt", 0),
            success=True,
        )

    def like_message(self, chat_id: str, message_id: str) -> bool:
        data = self._request(
            "POST",
            f"/api/fansly/{self.account_id}/chats/{chat_id}/messages/{message_id}/reactions",
            json={"type": 1},  # 1 = heart
        )
        return "data" in data

    # ─── MEDIA ───────────────────────────────────────────

    def upload_media(self, file_path: str) -> str:
        import os
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Upload file not found: {file_path}")

        with open(file_path, "rb") as f:
            data = self._request(
                "POST",
                f"/api/fansly/{self.account_id}/media/upload",
                files={"file": f},
            )
        return data["prefixed_id"]

    # ─── UNSUPPORTED IN CLOSED BETA ──────────────────────

    def list_albums(self) -> list[dict]:
        raise NotImplementedError(
            "Vault/album endpoints are not available on OnlyFansAPI's Fansly product yet (closed beta)."
        )

    def get_album_media(
        self, album_id: str, cursor: Optional[str] = None
    ) -> tuple[list[dict], Optional[str]]:
        raise NotImplementedError(
            "Vault/album endpoints are not available on OnlyFansAPI's Fansly product yet (closed beta)."
        )

    # ─── CLOSE ───────────────────────────────────────────

    def close(self):
        self.client.close()
```

Note on the test for `upload_media`: the test mocks `client.client.request` directly, so the real `files={"file": f}` multipart kwarg is passed through to the mock and never hits the network — this matches the pattern used by every other test in this file.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_fansly_api_client.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/fansly_api_client.py tests/test_fansly_api_client.py
git commit -m "feat: add FanslyApiClientImpl for OnlyFansAPI's Fansly product"
```

---

### Task 3: Provider factory

**Files:**
- Create: `src/client_factory.py`
- Create: `tests/test_client_factory.py`

**Interfaces:**
- Consumes: `ApifanslyClient`, `FanslyConfig` (from `src.fansly_client`), `FanslyApiClientImpl` (from `src.fansly_api_client`), both Task 1/2 outputs.
- Produces: `get_fansly_client(env: dict) -> FanslyApiClient` — takes an explicit env mapping (not `os.environ` directly) so it's trivially testable without env-var monkeypatching.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_client_factory.py`:

```python
"""Tests for the Fansly API provider factory."""
import pytest

from src.fansly_client import ApifanslyClient
from src.fansly_api_client import FanslyApiClientImpl
from src.client_factory import get_fansly_client


def test_defaults_to_apifansly_when_unset():
    client = get_fansly_client({"FANSLY_API_KEY": "k", "FANSLY_ACCOUNT_ID": "a"})
    assert isinstance(client, ApifanslyClient)


def test_returns_apifansly_when_explicitly_set():
    env = {"FANSLY_PROVIDER": "apifansly", "FANSLY_API_KEY": "k", "FANSLY_ACCOUNT_ID": "a"}
    client = get_fansly_client(env)
    assert isinstance(client, ApifanslyClient)
    assert client.config.api_key == "k"
    assert client.config.account_id == "a"


def test_returns_fanslyapi_when_set():
    env = {"FANSLY_PROVIDER": "fanslyapi", "FANSLY_API_KEY": "sk_test"}
    client = get_fansly_client(env)
    assert isinstance(client, FanslyApiClientImpl)
    assert client.api_key == "sk_test"


def test_raises_on_unknown_provider():
    env = {"FANSLY_PROVIDER": "not_a_real_provider", "FANSLY_API_KEY": "k"}
    with pytest.raises(ValueError, match="Unknown FANSLY_PROVIDER"):
        get_fansly_client(env)


def test_raises_when_apifansly_missing_account_id():
    env = {"FANSLY_PROVIDER": "apifansly", "FANSLY_API_KEY": "k"}
    with pytest.raises(ValueError, match="FANSLY_ACCOUNT_ID"):
        get_fansly_client(env)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_client_factory.py -v`
Expected: FAIL — `src.client_factory` doesn't exist yet.

- [ ] **Step 3: Implement `src/client_factory.py`**

```python
"""Selects the concrete Fansly API client from FANSLY_PROVIDER."""

from .fansly_client import FanslyApiClient, ApifanslyClient, FanslyConfig
from .fansly_api_client import FanslyApiClientImpl


def get_fansly_client(env: dict) -> FanslyApiClient:
    """Build the configured Fansly API client from an env-var mapping.

    env: a dict-like object (typically os.environ) with FANSLY_PROVIDER,
    FANSLY_API_KEY, and (for apifansly) FANSLY_ACCOUNT_ID.
    """
    provider = env.get("FANSLY_PROVIDER", "apifansly")
    api_key = env.get("FANSLY_API_KEY", "")

    if provider == "apifansly":
        account_id = env.get("FANSLY_ACCOUNT_ID", "")
        if not account_id:
            raise ValueError("FANSLY_ACCOUNT_ID is required for FANSLY_PROVIDER=apifansly")
        return ApifanslyClient(FanslyConfig(api_key=api_key, account_id=account_id))

    if provider == "fanslyapi":
        return FanslyApiClientImpl(api_key=api_key)

    raise ValueError(f"Unknown FANSLY_PROVIDER: '{provider}' (expected 'apifansly' or 'fanslyapi')")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_client_factory.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/client_factory.py tests/test_client_factory.py
git commit -m "feat: add FANSLY_PROVIDER client factory"
```

---

### Task 4: `bot.py` — unread-count pre-filter and `account_id` property usage

**Files:**
- Modify: `src/bot.py:13` (import), `src/bot.py:59` (account_id access), `src/bot.py:121-133` (`poll_and_process`)
- Modify: `tests/test_bot.py`

**Interfaces:**
- Consumes: `FanslyApiClient` (ABC, Task 1), `ChatInfo.unread_count` (existing field on `ChatInfo`, already populated by both clients).
- Produces: `FanslyBot.poll_and_process(filter_type="all", max_chats=50) -> bool` — now returns `True` if any chat had unread messages this cycle, `False` otherwise. `main.py` (Task 5) consumes this return value for idle backoff.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_bot.py` (the `bot` fixture already exists — reuse it):

```python
def test_poll_skips_list_messages_for_chats_with_no_unread(bot):
    """Chats with unread_count=0 should never trigger a list_messages call."""
    from src.fansly_client import ChatInfo
    bot.client.get_all_chats.return_value = [
        ChatInfo(chat_id="c1", partner_account_id="p1", partner_username="u1",
                 partner_display_name="U1", unread_count=0),
        ChatInfo(chat_id="c2", partner_account_id="p2", partner_username="u2",
                 partner_display_name="U2", unread_count=3),
    ]
    bot.client.list_messages.return_value = ([], None)

    bot.poll_and_process()

    bot.client.list_messages.assert_called_once_with("c2", limit=10)


def test_poll_returns_true_when_unread_found(bot):
    from src.fansly_client import ChatInfo
    bot.client.get_all_chats.return_value = [
        ChatInfo(chat_id="c1", partner_account_id="p1", partner_username="u1",
                 partner_display_name="U1", unread_count=2),
    ]
    bot.client.list_messages.return_value = ([], None)

    result = bot.poll_and_process()

    assert result is True


def test_poll_returns_false_when_no_unread_anywhere(bot):
    from src.fansly_client import ChatInfo
    bot.client.get_all_chats.return_value = [
        ChatInfo(chat_id="c1", partner_account_id="p1", partner_username="u1",
                 partner_display_name="U1", unread_count=0),
    ]

    result = bot.poll_and_process()

    assert result is False


def test_poll_returns_false_when_disabled(bot):
    bot.enabled = False
    result = bot.poll_and_process()
    assert result is False
```

Update the fixture and `test_bot_enabled_by_default`'s client construction (both currently `MagicMock(spec=FanslyClient)` with `client.config = FanslyConfig(...)`) to mock the ABC and the `account_id` property directly instead of going through `.config`:

```python
from src.fansly_client import FanslyApiClient, FanslyConfig
```

replaces the old `from src.fansly_client import FanslyClient, FanslyConfig` import line. Then wherever the file currently has:

```python
    client = MagicMock(spec=FanslyClient)
    client.config = FanslyConfig(api_key="test", account_id="test")
```

replace with:

```python
    client = MagicMock(spec=FanslyApiClient)
    client.account_id = "test"
```

(This occurs in the `bot` fixture and in `test_bot_enabled_by_default` — two locations.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_bot.py -v`
Expected: FAIL — new tests fail (no filtering/return-value logic yet); the two updated-fixture tests should still pass once the import/mock changes are in place (verify no `AttributeError` from the mock changes before moving on).

- [ ] **Step 3: Implement the filter and return value in `src/bot.py`**

Change the import at line 13:

```python
from .fansly_client import FanslyApiClient, ChatInfo, MessageInfo
```

Change line 59 (inside `__init__`):

```python
        self.account_id = client.account_id
```

Replace `poll_and_process` (lines 121-133):

```python
    def poll_and_process(self, filter_type: str = "all", max_chats: int = 50) -> bool:
        """Main loop: fetch chats, process chats with unread messages, send replies.

        Returns True if any chat had unread messages this cycle, False otherwise —
        the caller uses this to drive idle-adaptive polling.
        """
        if not self.enabled:
            logger.debug("Bot disabled — skipping poll cycle")
            return False

        chats = self.client.get_all_chats(filter_type=filter_type)
        unread_chats = [c for c in chats if c.unread_count > 0]
        logger.info(f"{len(chats)} chats total, {len(unread_chats)} with unread messages")

        for chat in unread_chats[:max_chats]:
            try:
                self._process_chat(chat)
            except Exception as e:
                logger.error(f"Error processing chat {chat.chat_id}: {e}")

        return len(unread_chats) > 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_bot.py -v`
Expected: PASS (all tests, old and new)

- [ ] **Step 5: Run the broader bot-dependent suite to check for regressions**

Run: `pytest tests/test_bot.py tests/test_bot_dedup.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/bot.py tests/test_bot.py
git commit -m "feat: filter poll cycle to chats with unread messages, return activity flag"
```

---

### Task 5: `main.py` — factory wiring, `verify_auth`, idle-adaptive backoff

**Files:**
- Modify: `src/main.py`
- Modify: `tests/test_main.py`
- Modify: `.env.example`

**Interfaces:**
- Consumes: `get_fansly_client(env)` (Task 3), `FanslyBot.poll_and_process() -> bool` (Task 4), `FanslyApiClient.verify_auth()` (Task 1/2).

- [ ] **Step 1: Write the failing tests**

In `tests/test_main.py`, the `mock_deps` fixture currently configures its `FanslyClient` mock via `patchers[-4].getter().return_value = mock_client` — this relies on `_patch.getter`, an undocumented `unittest.mock` internal that returns the *container* being patched (the module), not the replacement mock, and on fragile positional indexing into the 15-item `patchers` list. Rather than propagate that fragility into the provider-factory patch, rewrite the fixture to capture `.start()` return values directly — the standard, documented pattern.

Replace the entire `mock_deps` fixture body with:

```python
@pytest.fixture
def mock_deps(standard_env):
    """Patch low-level modules BEFORE src.main is imported."""
    patchers = [
        patch("src.persona.loader.PersonaLoader.load",
              return_value=MagicMock()),
        patch("src.web.dashboard.DashboardServer", MagicMock()),
        patch("src.memory.store.MessageStore"),
        patch("src.memory.llm.LLMFactExtractor"),
        # bot.py __init__ dependencies
        patch("src.bot.SequenceRepository", MagicMock()),
        patch("src.bot.ScriptLibrary", MagicMock()),
        patch("src.bot.ScriptEngine", MagicMock()),
        patch("src.bot.NoteExtractor", MagicMock()),
        patch("src.bot.FanClassifier", MagicMock()),
        patch("src.bot.TierClassifier", MagicMock()),
        patch("src.bot.PersonaValidator", MagicMock()),
        patch("src.bot.PushPullEngine", MagicMock()),
        # note repo with engine.url that stringifies
        patch(
            "src.notes.repository.FanNoteRepository",
            return_value=_make_note_repo(),
        ),
    ]
    for p in patchers:
        p.start()

    # FanslyBot itself — so reload doesn't re-import the real class
    bot_patcher = patch("src.bot.FanslyBot")
    mock_bot_cls = bot_patcher.start()

    # client factory — replaces direct client construction in main.py
    factory_patcher = patch("src.client_factory.get_fansly_client")
    mock_get_client = factory_patcher.start()

    mock_client = MagicMock()
    mock_client.verify_auth.return_value = True
    mock_get_client.return_value = mock_client

    # Configure FanslyBot mock — default: stop after 1 call
    bot, _ = _make_controlled_bot(
        poll_side_effects=[None],
        module_ref=lambda: __import__("src.main"),
    )
    mock_bot_cls.return_value = bot

    all_patchers = patchers + [bot_patcher, factory_patcher]

    yield {
        "client": mock_client,
        "client_cls": mock_get_client,
        "bot": bot,
        "bot_cls": mock_bot_cls,
    }

    for p in all_patchers:
        p.stop()
```

This is a straight behavioral equivalent of the original fixture (same set of patched targets, same default return values) — the only semantic changes are: `FanslyClient` construction → `get_fansly_client()` call, and `_request` → `verify_auth` as the mocked auth-check surface. `mock_deps["client"]` and `mock_deps["bot"]` keep the same meaning every existing test already relies on.

Update every reference to `mock_deps["client"]._request.side_effect = ...` in `TestStartupAuthValidation` (there are 4: `test_auth_check_exits_on_401`, `test_auth_check_exits_on_402`, `test_auth_check_logs_critical_on_401`, `test_auth_check_logs_critical_on_402`, `test_auth_check_not_called_on_other_errors`, `test_auth_check_exits_before_poll_loop`) to use `mock_deps["client"].verify_auth.side_effect = ...` instead of `mock_deps["client"]._request.side_effect = ...`.

Add new idle-backoff tests to `TestExponentialBackoff` (this class already has a `_run_loop` helper — reuse it):

```python
class TestIdleAdaptiveBackoff:
    """Poll interval backs off when idle (no unread), resets fast when active."""

    def _run_loop_idle(self, module, poll_return_values, poll_interval="2",
                        idle_backoff_max="60"):
        os.environ["POLL_INTERVAL"] = poll_interval
        os.environ["IDLE_BACKOFF_MAX"] = idle_backoff_max

        bot = MagicMock()
        bot.sequence_repo = MagicMock()
        iter_idx = [0]

        def _poll():
            idx = iter_idx[0]
            iter_idx[0] += 1
            if idx >= len(poll_return_values):
                module.running = False
                return False
            return poll_return_values[idx]

        bot.poll_and_process = _poll
        module.FanslyBot = MagicMock(return_value=bot)

        importlib.reload(module)
        return iter_idx[0]

    def test_idle_cycles_increase_sleep_interval(self, module):
        """Three consecutive idle (False) cycles should still complete without error —
        interval grows but the loop keeps running."""
        iterations = self._run_loop_idle(
            module, [False, False, False], poll_interval="2", idle_backoff_max="60"
        )
        assert iterations >= 3

    def test_activity_resets_idle_backoff(self, module):
        """An active (True) cycle after idle ones resets the fast interval —
        loop should keep completing cycles without error."""
        iterations = self._run_loop_idle(
            module, [False, False, True, False], poll_interval="2", idle_backoff_max="60"
        )
        assert iterations >= 4
```

Update `TestCreditAwarenessLogging.test_warns_if_exceeding_pro_plan` — the message text is changing (see Step 3), so update the assertion:

```python
    def test_warns_if_exceeding_basic_plan(self, module, caplog):
        """If estimated requests >20000/day (Basic plan credits/mo), log a warning."""
        os.environ["POLL_INTERVAL"] = "2"
        importlib.reload(module)

        assert any(
            "exceed Basic plan" in r.message
            for r in caplog.records
        ), "Expected warning about exceeding Basic plan credits"
```

(Rename replaces the old `test_warns_if_exceeding_pro_plan` test.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_main.py -v`
Expected: FAIL — factory not wired in yet, `IDLE_BACKOFF_MAX` env var not read yet, message text not updated yet.

- [ ] **Step 3: Implement the changes in `src/main.py`**

Change the import block (line 24):

```python
from .fansly_client import AuthError, PaymentRequiredError
from .client_factory import get_fansly_client
```

Change the config section (lines 43-49) — add `FANSLY_PROVIDER` passthrough and `IDLE_BACKOFF_MAX`, raise the default `POLL_INTERVAL`:

```python
API_KEY = os.getenv("FANSLY_API_KEY", "") or os.getenv("APIFANSLY_API_KEY", "")
ACCOUNT_ID = os.getenv("FANSLY_ACCOUNT_ID", "")
CREATOR_ID = os.getenv("CREATOR_ID", "sunny_charm")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "60"))   # seconds, fast/active interval
IDLE_BACKOFF_MAX = int(os.getenv("IDLE_BACKOFF_MAX", "600"))  # cap for idle backoff
MAX_BACKOFF = int(os.getenv("MAX_BACKOFF", "600"))      # max seconds between polls on error
DB_URL = os.getenv("DATABASE_URL", "sqlite:///data/fansly_bot.db")
PORT = int(os.getenv("PORT", "8080"))
```

Change the validation check (line 51-53) — `ACCOUNT_ID` is only required for the `apifansly` provider now, so let the factory validate it instead:

```python
if not API_KEY:
    logger.error("Missing FANSLY_API_KEY. Set as env var.")
    sys.exit(1)
```

Change client construction (lines 57-58):

```python
client = get_fansly_client(os.environ)
```

Change the startup auth validation block (lines 95-108) to call `verify_auth()` instead of the private `_request`:

```python
try:
    client.verify_auth()
    logger.info("API authentication verified")
    api_ok = True
except AuthError as e:
    logger.warning(f"API AUTH FAILED: {e}. Dashboard will still work, bot will not poll.")
    api_ok = False
except PaymentRequiredError as e:
    logger.warning(f"API PAYMENT REQUIRED: {e}. Bot will not poll until credits added.")
    api_ok = False
except Exception as e:
    logger.warning(f"API check failed: {e}. Bot will not poll.")
    api_ok = False
```

Change the credit-awareness block (lines 116-124) to use accurate, verified numbers (Basic = 20,000 credits/mo, not the old made-up "Pro plan ... 24K"):

```python
# ─── Credit Awareness ──────────────────────────────────

estimated_daily = 86400 // POLL_INTERVAL
logger.info(
    f"Estimated API requests (worst case, no idle backoff): ~{estimated_daily}/day "
    f"at {POLL_INTERVAL}s interval"
)
if estimated_daily > 20000:
    logger.warning(
        f"At ~{estimated_daily} requests/day worst case, you may exceed Basic plan limits "
        f"(20,000 credits/mo). Idle-adaptive backoff reduces real usage below this when "
        f"chats are quiet, but consider raising POLL_INTERVAL if this concerns you."
    )
```

Replace the main loop (lines 169-190) with idle-adaptive backoff alongside the existing failure backoff:

```python
consecutive_failures = 0
consecutive_idle_cycles = 0

while running:
    had_activity = False
    try:
        had_activity = bot.poll_and_process()
        consecutive_failures = 0  # reset on success
    except (AuthError, PaymentRequiredError) as e:
        logger.critical(f"Fatal API error: {e}. Shutting down.")
        running = False
        break
    except Exception as e:
        consecutive_failures += 1
        logger.error(f"Error in main loop ({consecutive_failures} consecutive): {e}", exc_info=True)

    # Failure backoff takes priority over idle backoff for this cycle.
    if consecutive_failures > 0:
        consecutive_idle_cycles = 0
        backoff = min(POLL_INTERVAL * (2 ** (consecutive_failures - 1)), MAX_BACKOFF)
        logger.warning(f"Backoff: sleeping {backoff}s (failure #{consecutive_failures})")
    elif had_activity:
        consecutive_idle_cycles = 0
        backoff = POLL_INTERVAL
    else:
        consecutive_idle_cycles += 1
        backoff = min(POLL_INTERVAL * (2 ** consecutive_idle_cycles), IDLE_BACKOFF_MAX)
        logger.debug(f"Idle: sleeping {backoff}s (idle cycle #{consecutive_idle_cycles})")

    sleep_with_interrupt(backoff)

logger.info("Bot stopped.")
```

Also update the log line at 166-167 to mention the idle cap:

```python
logger.info(f"Account: {ACCOUNT_ID or '(resolved via API)'}, Poll interval: {POLL_INTERVAL}s")
logger.info(f"Max failure backoff: {MAX_BACKOFF}s, max idle backoff: {IDLE_BACKOFF_MAX}s")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_main.py -v`
Expected: PASS (all tests, old and new)

- [ ] **Step 5: Update `.env.example`**

Add to `.env.example` (after the existing `POLL_INTERVAL` line):

```
# Which Fansly API provider to use: apifansly (x-api-key, needs FANSLY_ACCOUNT_ID)
# or fanslyapi (Bearer token, account resolved automatically via the API)
FANSLY_PROVIDER=apifansly

# Idle backoff cap in seconds — how long polling backs off to when no chats
# have unread messages. Resets to POLL_INTERVAL the instant activity resumes.
IDLE_BACKOFF_MAX=600
```

- [ ] **Step 6: Run the full test suite**

Run: `pytest tests/ -q`
Expected: PASS — every test in the repo, no regressions.

- [ ] **Step 7: Commit**

```bash
git add src/main.py tests/test_main.py .env.example
git commit -m "feat: wire provider factory into main.py, add idle-adaptive polling backoff"
```

---

### Task 6: Railway deployment — switch the live bot over

**Files:** none (operational task, run after Task 5 is merged and the full suite is green)

This task is done with you present, not autonomously — it touches production env vars and the live bot.

- [ ] **Step 1: Confirm your OnlyFansAPI key and Fansly account connection**

Log into `app.onlyfansapi.com`, confirm the Fansly account shows as connected under Account/API Keys, and copy the Bearer-style API key from there (the console is the source of truth for the exact key format — sanity-check it there rather than assuming the key already shared is correctly formatted).

- [ ] **Step 2: Set Railway env vars** (via `railway variable set`, on the `sunny-charm` service, `fansly-bot` project — already linked)

```bash
railway variable set FANSLY_PROVIDER=fanslyapi --service sunny-charm
railway variable set FANSLY_API_KEY=<the confirmed Bearer token> --service sunny-charm
railway variable set POLL_INTERVAL=60 --service sunny-charm
railway variable set IDLE_BACKOFF_MAX=600 --service sunny-charm
```

Leave `FANSLY_ACCOUNT_ID` set to whatever it currently is — it's unused by the `fanslyapi` provider path but keeps `apifansly` rollback ready.

- [ ] **Step 2: Deploy and verify**

```bash
railway up --detach -m "switch Fansly API provider to fanslyapi"
```

Poll `railway deployment list --json` until `status` is `SUCCESS`, then:

```bash
railway logs --service sunny-charm --lines 100 --search "API authentication verified"
```

Confirm the log line appears (not "API AUTH FAILED" / "API PAYMENT REQUIRED") and that `bot.enabled` ends up `true` (check the dashboard toggle or `railway logs --search "Bot enabled state"`).

- [ ] **Step 3: Rollback path, if needed**

```bash
railway variable set FANSLY_PROVIDER=apifansly --service sunny-charm
railway up --detach -m "rollback to apifansly provider"
```

---

## Self-Review Notes

- **Spec coverage**: every confirmed endpoint from the design spec (list chats, list messages, send message, send PPV, like/react, upload media, list accounts) has a corresponding method and test in Task 2. The idle-adaptive polling and unread-filter decisions from the spec are implemented in Tasks 4-5. Vault/earnings gaps raise `NotImplementedError` per the spec's decision (Task 2). Webhooks are explicitly out of scope, matching the spec.
- **Type consistency checked**: `send_ppv(chat_id, content, media_id, price, preview_id=None)` matches the call site at `bot.py:540-546` exactly; `account_id` property name is consistent across the ABC (Task 1), `FanslyApiClientImpl` (Task 2), and `bot.py:59` (Task 4); `poll_and_process() -> bool` return value is defined in Task 4 and consumed in Task 5 with matching semantics (`True` = had activity).
- **No placeholders**: every step has real code, no "add error handling" or "TBD" markers.
