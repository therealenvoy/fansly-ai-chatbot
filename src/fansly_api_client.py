"""Fansly API Client — OnlyFansAPI's Fansly product (app.onlyfansapi.com).

Base URL: https://app.onlyfansapi.com
Auth: Authorization: Bearer <token>
Docs: https://docs.onlyfansapi.com/api-reference/fansly (closed beta)

Confirmed gaps in this closed beta: no vault/album endpoints, no documented
paid-message fields, and wallet transactions have no fan/message attribution.
Unsupported operations fail closed rather than fabricating provider behavior.
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
    ProviderCapabilities,
    UnsupportedProviderFeature,
    WalletTransaction,
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
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_free_media_messages=True,
            supports_paid_messages=False,
            supports_attributed_purchases=False,
            supports_wallet_transactions=True,
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

    def list_chats_page(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        order: str = "newest",
    ) -> tuple[list[ChatInfo], Optional[int]]:
        """Fetch one documented OnlyFansAPI Fansly chat page."""
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if order not in {"newest", "oldest", "unread"}:
            raise ValueError("order must be newest, oldest, or unread")

        data = self._request(
            "GET",
            f"/api/fansly/{self.account_id}/chats",
            params={"limit": limit, "offset": offset, "order": order},
        )
        inner = data.get("data", {})
        chats_raw = inner.get("data", [])
        accounts = {
            account["id"]: account
            for account in inner.get("aggregationData", {}).get(
                "accounts", []
            )
        }
        chats: list[ChatInfo] = []
        for chat in chats_raw:
            partner_id = chat.get("partnerAccountId", "")
            acc_info = accounts.get(partner_id, {})
            locations = acc_info.get("avatar", {}).get("locations", [])
            chats.append(
                ChatInfo(
                    chat_id=chat["groupId"],
                    partner_account_id=partner_id,
                    partner_username=chat.get(
                        "partnerUsername",
                        acc_info.get("username", ""),
                    ),
                    partner_display_name=acc_info.get(
                        "displayName",
                        chat.get("partnerUsername", ""),
                    ),
                    unread_count=chat.get("unreadCount", 0),
                    last_message_id=chat.get("lastMessageId"),
                    last_unread_message_id=chat.get(
                        "lastUnreadMessageId"
                    ),
                    subscription_tier_id=chat.get("subscriptionTierId"),
                    avatar_url=(
                        locations[0].get("location") if locations else None
                    ),
                )
            )
        next_offset = (
            offset + len(chats_raw)
            if inner.get("hasMore") and chats_raw
            else None
        )
        return chats, next_offset

    def get_all_chats(self, filter_type: str = "all") -> list[ChatInfo]:
        """Paginate every page using OnlyFansAPI's offset contract."""
        order = filter_type if filter_type in {
            "newest",
            "oldest",
            "unread",
        } else "newest"
        all_chats: list[ChatInfo] = []
        offset: Optional[int] = 0
        while offset is not None:
            chats, offset = self.list_chats_page(
                limit=100,
                offset=offset,
                order=order,
            )
            all_chats.extend(chats)
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
        if price is not None or access_type:
            raise UnsupportedProviderFeature(
                "OnlyFansAPI's documented Fansly send endpoint does not "
                "currently expose price or access/paywall fields"
            )
        if not content.strip() and not media_ids:
            raise ValueError(
                "Fansly messages require text, at least one media ID, or both"
            )
        body = {"text": content}
        if media_ids:
            ids = [m["mediaId"] for m in media_ids]
            if any(
                not isinstance(media_id, str)
                or not media_id.startswith("fansly_media_")
                for media_id in ids
            ):
                raise ValueError(
                    "Fansly media messages require fansly_media_ upload IDs"
                )
            body["mediaFiles"] = ids

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
        raise UnsupportedProviderFeature(
            "Paid Fansly chat messages are not present in the current "
            "OnlyFansAPI Fansly send-message contract"
        )

    def list_wallet_transactions_page(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[WalletTransaction], Optional[int]]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        payload = self._request(
            "GET",
            f"/api/fansly/{self.account_id}/earnings/transactions",
            params={"limit": limit, "offset": offset},
        )
        inner = payload.get("data", {})
        rows = inner.get("data", [])
        transactions = [
            WalletTransaction(
                transaction_id=str(row["transactionId"]),
                transaction_type=int(row["type"]),
                destination=str(row.get("destination", "")),
                amount_millis=int(row.get("amount", 0)),
                destination_tax_millis=int(
                    row.get("destinationTax", 0)
                ),
                new_balance_millis=int(row.get("newBalance", 0)),
                created_at=float(row.get("createdAt", 0)),
                status=int(row.get("status", 0)),
            )
            for row in rows
        ]
        total = int(inner.get("total", len(rows)))
        next_offset = offset + len(rows)
        return (
            transactions,
            next_offset if rows and next_offset < total else None,
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
