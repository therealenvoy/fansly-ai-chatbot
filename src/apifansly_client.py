"""Client for apifansly.com's managed Fansly API.

Base URL: https://v1.apifansly.com/api/fansly
Auth: x-api-key
Docs: https://docs.apifansly.com

This provider documents paid chat media and vault browsing, which are required
for fully automated PPV sequences.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import time
from typing import Any

import httpx

from .fansly_client import (
    AuthError,
    ChatInfo,
    FanslyApiClient,
    MessageInfo,
    NotFoundError,
    PaymentRequiredError,
    ProviderCapabilities,
    SentMessage,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://v1.apifansly.com/api/fansly"


@dataclass(frozen=True)
class ApifanslyConfig:
    api_key: str
    account_id: str
    webhook_token: str = ""
    base_url: str = BASE_URL
    timeout: float = 30.0
    max_retries: int = 3
    retry_delay: float = 1.0


class ResponseParser:
    """Extract the provider's nested response and pagination cursor."""

    @staticmethod
    def parse(payload: dict, *, default: Any = None) -> Any:
        if not isinstance(payload, dict):
            raise ValueError("Unexpected APIFansly response type")
        outer = payload.get("data")
        if not isinstance(outer, dict):
            return default
        inner = outer.get("data")
        if not isinstance(inner, dict):
            return default
        return inner.get("response", default)

    @staticmethod
    def cursor(payload: dict) -> str | None:
        outer = payload.get("data", {})
        if not isinstance(outer, dict):
            return None
        value = outer.get("nextCursor")
        return str(value) if value not in (None, "") else None


class ApifanslyClient(FanslyApiClient):
    """Synchronous HTTP adapter for apifansly.com."""

    def __init__(self, config: ApifanslyConfig):
        self.config = config
        self._creator_fansly_id: str | None = None
        headers = {"Content-Type": "application/json"}
        if config.api_key.strip():
            headers["x-api-key"] = config.api_key.strip()
        self.client = httpx.Client(
            base_url=config.base_url,
            headers=headers,
            timeout=config.timeout,
        )

    @property
    def provider_name(self) -> str:
        return "APIFansly"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_free_media_messages=True,
            supports_paid_messages=True,
            supports_attributed_purchases=(
                len(self.config.webhook_token.strip()) >= 32
            ),
            supports_wallet_transactions=False,
            supports_vault_albums=True,
        )

    @property
    def account_id(self) -> str:
        return self.config.account_id.strip()

    @property
    def creator_fansly_id(self) -> str:
        if self._creator_fansly_id is None:
            self._resolve_creator_id()
        return self._creator_fansly_id

    def _validate_credentials(self) -> None:
        if not self.config.api_key.strip():
            raise AuthError("APIFANSLY_API_KEY is not configured")
        if not self.account_id:
            raise AuthError("FANSLY_ACCOUNT_ID is not configured")

    def _resolve_creator_id(self) -> None:
        self._validate_credentials()
        payload = self._request("GET", f"/{self.account_id}/me")
        response = ResponseParser.parse(payload, default={})
        account = (
            response.get("account", response)
            if isinstance(response, dict)
            else {}
        )
        creator_id = account.get("id")
        if not creator_id:
            raise AuthError(
                "Connected APIFansly account did not expose its Fansly ID"
            )
        self._creator_fansly_id = str(creator_id)

    def verify_auth(self) -> bool:
        self._resolve_creator_id()
        return True

    def _request(self, method: str, path: str, **kwargs) -> dict:
        self._validate_credentials()
        for attempt in range(self.config.max_retries):
            try:
                response = self.client.request(method, path, **kwargs)
                if response.status_code in (401, 403):
                    raise AuthError(
                        f"Authentication failed: {response.status_code} "
                        f"on {method} {path}"
                    )
                if response.status_code == 402:
                    raise PaymentRequiredError(
                        f"Payment required on {method} {path}"
                    )
                if response.status_code == 404:
                    raise NotFoundError(f"Resource not found: {path}")
                if response.status_code == 429:
                    if attempt == self.config.max_retries - 1:
                        response.raise_for_status()
                    retry_after = float(
                        response.headers.get(
                            "Retry-After",
                            self.config.retry_delay * (attempt + 1),
                        )
                    )
                    time.sleep(max(0.0, retry_after))
                    continue
                if response.status_code >= 500:
                    if attempt == self.config.max_retries - 1:
                        response.raise_for_status()
                    time.sleep(self.config.retry_delay * (attempt + 1))
                    continue
                response.raise_for_status()
                payload = response.json()
                status = payload.get("statusCode") if isinstance(payload, dict) else None
                if status in (401, 403):
                    raise AuthError(payload.get("message", "Authentication failed"))
                if status == 402:
                    raise PaymentRequiredError(
                        payload.get("message", "Payment required")
                    )
                if status and not 200 <= int(status) < 300:
                    raise httpx.HTTPStatusError(
                        payload.get("message", "APIFansly request failed"),
                        request=response.request,
                        response=response,
                    )
                return payload
            except (AuthError, PaymentRequiredError, NotFoundError):
                raise
            except (httpx.TimeoutException, httpx.ConnectError):
                if attempt == self.config.max_retries - 1:
                    raise
                time.sleep(self.config.retry_delay * (attempt + 1))
        raise RuntimeError(
            f"APIFansly request failed after {self.config.max_retries} attempts"
        )

    def list_chats_page(
        self,
        *,
        limit: int = 100,
        offset: int | str = 0,
        order: str = "newest",
    ) -> tuple[list[ChatInfo], int | str | None]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if order not in {"newest", "oldest", "unread"}:
            raise ValueError("order must be newest, oldest, or unread")
        params: dict[str, Any] = {"filter": "all", "sort": order}
        if offset not in (0, "", None):
            params["cursor"] = offset
        payload = self._request(
            "GET",
            f"/{self.account_id}/chats",
            params=params,
        )
        response = ResponseParser.parse(payload, default={})
        rows = response.get("data", []) if isinstance(response, dict) else []
        accounts = {
            str(account.get("id")): account
            for account in response.get("aggregationData", {}).get(
                "accounts", []
            )
            if isinstance(account, dict)
        }
        chats: list[ChatInfo] = []
        for row in rows:
            partner_id = str(row.get("partnerAccountId", ""))
            account = accounts.get(partner_id, {})
            locations = account.get("avatar", {}).get("locations", [])
            chats.append(
                ChatInfo(
                    chat_id=str(row["groupId"]),
                    partner_account_id=partner_id,
                    partner_username=str(
                        row.get(
                            "partnerUsername",
                            account.get("username", ""),
                        )
                    ),
                    partner_display_name=str(
                        account.get(
                            "displayName",
                            row.get("partnerUsername", ""),
                        )
                    ),
                    unread_count=int(row.get("unreadCount", 0) or 0),
                    last_message_id=(
                        str(row["lastMessageId"])
                        if row.get("lastMessageId")
                        else None
                    ),
                    last_unread_message_id=(
                        str(row["lastUnreadMessageId"])
                        if row.get("lastUnreadMessageId")
                        else None
                    ),
                    subscription_tier_id=(
                        str(row["subscriptionTierId"])
                        if row.get("subscriptionTierId")
                        else None
                    ),
                    avatar_url=(
                        locations[0].get("location")
                        if locations
                        else account.get("avatar", {}).get("location")
                    ),
                )
            )
        return chats, ResponseParser.cursor(payload)

    def get_all_chats(self, filter_type: str = "all") -> list[ChatInfo]:
        all_chats: list[ChatInfo] = []
        cursor: int | str | None = 0
        while cursor is not None:
            page, cursor = self.list_chats_page(
                limit=100,
                offset=cursor,
                order=(
                    filter_type
                    if filter_type in {"newest", "oldest", "unread"}
                    else "newest"
                ),
            )
            all_chats.extend(page)
        return all_chats

    def list_messages(
        self,
        chat_id: str,
        limit: int = 10,
        cursor: str | None = None,
    ) -> tuple[list[MessageInfo], str | None]:
        params: dict[str, Any] = {"limit": min(max(limit, 1), 10)}
        if cursor:
            params["cursor"] = cursor
        payload = self._request(
            "GET",
            f"/{self.account_id}/chats/{chat_id}/messages",
            params=params,
        )
        response = ResponseParser.parse(payload, default={})
        rows = (
            response.get("messages", [])
            if isinstance(response, dict)
            else []
        )
        messages = [
            MessageInfo(
                message_id=str(row["id"]),
                content=str(row.get("content", "")),
                sender_id=str(row.get("senderId", "")),
                created_at=float(row.get("createdAt", 0) or 0),
                is_from_fan=(
                    str(row.get("senderId", ""))
                    != self.creator_fansly_id
                ),
                has_attachments=bool(row.get("attachments")),
                total_tip=float(row.get("totalTipAmount", 0) or 0),
                attachments=list(row.get("attachments", [])),
            )
            for row in rows
        ]
        next_cursor = (
            str(response.get("cursor"))
            if isinstance(response, dict) and response.get("cursor")
            else None
        )
        return messages, next_cursor

    def send_message(
        self,
        chat_id: str,
        content: str,
        media_ids: list[dict] | None = None,
        access_type: list[str] | None = None,
        price: float | None = None,
    ) -> SentMessage:
        if not content.strip():
            raise ValueError("APIFansly messages require non-empty text")
        body: dict[str, Any] = {"content": content}
        if media_ids:
            normalized = []
            for item in media_ids:
                media_id = item.get("mediaId")
                if not isinstance(media_id, str) or not media_id.strip():
                    raise ValueError("Each media attachment requires mediaId")
                entry = {"mediaId": media_id.strip()}
                preview_id = item.get("previewId")
                if preview_id:
                    entry["previewId"] = str(preview_id)
                normalized.append(entry)
            body["mediaIds"] = normalized
        if access_type:
            allowed = {
                "ppv",
                "subscription",
                "follow",
                "list",
                "limited_time",
            }
            if not set(access_type).issubset(allowed):
                raise ValueError("Unsupported APIFansly media access type")
            body["access_type"] = list(access_type)
        if price is not None:
            if "ppv" not in (access_type or []):
                raise ValueError("price requires ppv access_type")
            if not media_ids:
                raise ValueError("PPV messages require attached media")
            if not 1 <= float(price) <= 500:
                raise ValueError("PPV price must be between $1 and $500")
            body["price"] = float(price)
        payload = self._request(
            "POST",
            f"/{self.account_id}/chats/{chat_id}/messages",
            json=body,
        )
        message = ResponseParser.parse(payload, default={})
        if not isinstance(message, dict) or not message.get("id"):
            raise ValueError("APIFansly send response did not include a message ID")
        purchase_reference_id = None
        attachments = message.get("attachments", [])
        if isinstance(attachments, list):
            for attachment in attachments:
                if not isinstance(attachment, dict):
                    continue
                content_id = attachment.get("contentId")
                if content_id not in (None, ""):
                    purchase_reference_id = str(content_id)
                    break
        return SentMessage(
            message_id=str(message["id"]),
            content=str(message.get("content", content)),
            created_at=float(message.get("createdAt", 0) or 0),
            success=True,
            purchase_reference_id=purchase_reference_id,
        )

    def send_ppv(
        self,
        chat_id: str,
        content: str,
        media_id: str,
        price: float,
        preview_id: str | None = None,
    ) -> SentMessage:
        media = {"mediaId": media_id}
        if preview_id:
            media["previewId"] = preview_id
        return self.send_message(
            chat_id,
            content,
            media_ids=[media],
            access_type=["ppv"],
            price=price,
        )

    def like_message(self, chat_id: str, message_id: str) -> bool:
        payload = self._request(
            "POST",
            f"/{self.account_id}/chats/{chat_id}/messages/{message_id}/like",
        )
        return int(payload.get("statusCode", 0)) == 200

    def upload_media(self, file_path: str) -> str:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Upload file not found: {file_path}")
        with open(file_path, "rb") as handle:
            response = self.client.post(
                f"/{self.account_id}/media/upload",
                headers={"x-api-key": self.config.api_key.strip()},
                files={"file": handle},
                timeout=120.0,
            )
        response.raise_for_status()
        payload = response.json()
        media_id = (
            ResponseParser.parse(payload, default={}).get("mediaId")
            if isinstance(ResponseParser.parse(payload, default={}), dict)
            else None
        )
        if not media_id:
            media_id = payload.get("data", {}).get("mediaId")
        if not media_id:
            raise ValueError("APIFansly upload response did not include mediaId")
        return str(media_id)

    def list_albums(self) -> list[dict]:
        payload = self._request(
            "GET",
            f"/{self.account_id}/vault/albums",
        )
        response = ResponseParser.parse(payload, default={})
        if isinstance(response, list):
            return response
        if isinstance(response, dict):
            return list(response.get("albums", []))
        return []

    def get_album_media(
        self,
        album_id: str,
        cursor: str | None = None,
    ) -> tuple[list[dict], str | None]:
        params = {"cursor": cursor} if cursor else None
        payload = self._request(
            "GET",
            f"/{self.account_id}/vault/albums/{album_id}/media",
            params=params,
        )
        response = ResponseParser.parse(payload, default=[])
        if isinstance(response, list):
            media = response
            response_cursor = None
        elif isinstance(response, dict):
            media = list(response.get("media", response.get("data", [])))
            response_cursor = response.get("cursor")
        else:
            media = []
            response_cursor = None
        return (
            media,
            str(response_cursor)
            if response_cursor not in (None, "")
            else ResponseParser.cursor(payload),
        )

    def close(self) -> None:
        self.client.close()
