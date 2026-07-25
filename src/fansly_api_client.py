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
        self.api_key = api_key.strip()
        self.timeout = timeout
        self._account_id: Optional[str] = None
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        self.client = httpx.Client(
            base_url=BASE_URL,
            headers=headers,
            timeout=timeout,
        )

    @property
    def account_id(self) -> str:
        if self._account_id is None:
            self._resolve_account_id()
        return self._account_id

    def _resolve_account_id(self):
        if not self.api_key:
            raise AuthError("FANSLY_API_KEY is not configured")
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
