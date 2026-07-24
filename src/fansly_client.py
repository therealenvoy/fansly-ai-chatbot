"""
Fansly API Client — integration layer between apifansly.com and our 17-system chatbot.

Base URL: https://v1.apifansly.com/api/fansly
Auth: x-api-key header
Docs: https://docs.apifansly.com
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://v1.apifansly.com/api/fansly"


@dataclass
class FanslyConfig:
    api_key: str
    account_id: str
    base_url: str = BASE_URL
    timeout: float = 30.0
    max_retries: int = 3
    retry_delay: float = 2.0
    rate_limit_safety: float = 0.1  # 100ms padding between requests


@dataclass
class ChatInfo:
    """Parsed chat data for bot consumption."""
    chat_id: str  # groupId from API
    partner_account_id: str
    partner_username: str
    partner_display_name: str
    unread_count: int = 0
    last_message_id: Optional[str] = None
    subscription_tier_id: Optional[str] = None
    avatar_url: Optional[str] = None


@dataclass
class MessageInfo:
    """Parsed message for bot processing."""
    message_id: str
    content: str
    sender_id: str
    created_at: float  # unix timestamp
    is_from_fan: bool  # True if fan sent it, False if creator sent it
    has_attachments: bool = False
    total_tip: float = 0.0
    attachments: list[dict] = field(default_factory=list)


@dataclass
class SentMessage:
    """Result of sending a message."""
    message_id: str
    content: str
    created_at: float
    success: bool


class FanslyClient:
    """HTTP client for apifansly.com API."""

    def __init__(self, config: FanslyConfig):
        self.config = config
        self._client: Optional[httpx.Client] = None
        self._last_request_time: float = 0

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.config.base_url,
                headers={
                    "x-api-key": self.config.api_key,
                    "Content-Type": "application/json",
                },
                timeout=self.config.timeout,
            )
        return self._client

    def _rate_limit_wait(self):
        """Ensure minimum gap between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.config.rate_limit_safety:
            time.sleep(self.config.rate_limit_safety - elapsed)
        self._last_request_time = time.time()

    def _request(self, method: str, path: str, **kwargs) -> dict:
        """Make API request with retry + rate limit + error handling."""
        self._rate_limit_wait()

        for attempt in range(self.config.max_retries):
            try:
                response = self.client.request(method, path, **kwargs)
                data = response.json()

                if response.status_code == 429:
                    retry_after = int(response.headers.get("X-RateLimit-Retry-After", 5))
                    logger.warning(f"Rate limited, retrying in {retry_after}s")
                    time.sleep(retry_after)
                    continue

                if response.status_code >= 500:
                    logger.warning(f"Server error {response.status_code}, attempt {attempt + 1}")
                    time.sleep(self.config.retry_delay * (attempt + 1))
                    continue

                response.raise_for_status()
                return data

            except httpx.TimeoutException:
                logger.warning(f"Timeout on attempt {attempt + 1}")
                if attempt < self.config.max_retries - 1:
                    time.sleep(self.config.retry_delay * (attempt + 1))
                else:
                    raise

        raise Exception(f"Request failed after {self.config.max_retries} attempts")

    # ─── CHATS ───────────────────────────────────────────

    def list_chats(
        self,
        filter_type: str = "all",
        sort: str = "newest",
        cursor: Optional[str] = None,
        search: Optional[str] = None,
    ) -> tuple[list[ChatInfo], Optional[str]]:
        """Get all chats for the connected account. Returns (chats, next_cursor)."""
        params = {"filter": filter_type, "sort": sort}
        if cursor:
            params["cursor"] = cursor
        if search:
            params["search"] = search

        data = self._request("GET", f"/{self.config.account_id}/chats", params=params)
        response = data["data"]["data"]["response"]
        chats_raw = response.get("data", [])
        next_cursor = data["data"].get("nextCursor")

        # Build lookup for account details
        accounts = {}
        for acc in response.get("aggregationData", {}).get("accounts", []):
            accounts[acc["id"]] = acc

        chats = []
        for chat in chats_raw:
            partner_id = chat.get("partnerAccountId", "")
            acc_info = accounts.get(partner_id, {})
            avatar_url = None
            avatar_obj = acc_info.get("avatar", {})
            locations = avatar_obj.get("locations", [])
            if locations:
                avatar_url = locations[0].get("location")

            chats.append(ChatInfo(
                chat_id=chat["groupId"],
                partner_account_id=partner_id,
                partner_username=chat.get("partnerUsername", acc_info.get("username", "")),
                partner_display_name=acc_info.get("displayName", chat.get("partnerUsername", "")),
                unread_count=chat.get("unreadCount", 0),
                last_message_id=chat.get("lastMessageId"),
                subscription_tier_id=chat.get("subscriptionTierId"),
                avatar_url=avatar_url,
            ))

        return chats, next_cursor

    def get_all_chats(self, filter_type: str = "all") -> list[ChatInfo]:
        """Paginate through all chats."""
        all_chats = []
        cursor = None
        while True:
            chats, cursor = self.list_chats(filter_type=filter_type, cursor=cursor)
            all_chats.extend(chats)
            if not cursor:
                break
        return all_chats

    # ─── MESSAGES ────────────────────────────────────────

    def list_messages(
        self, chat_id: str, limit: int = 10, cursor: Optional[str] = None
    ) -> tuple[list[MessageInfo], Optional[str]]:
        """Get messages from a chat. Returns (messages, next_cursor)."""
        params = {"limit": min(limit, 10)}
        if cursor:
            params["cursor"] = cursor

        data = self._request(
            "GET", f"/{self.config.account_id}/chats/{chat_id}/messages", params=params
        )
        response = data["data"]["data"]["response"]
        messages_raw = response.get("messages", [])
        next_cursor = response.get("cursor")

        messages = []
        for msg in messages_raw:
            is_fan = msg.get("senderId") != self.config.account_id
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

        return messages, next_cursor

    def send_message(
        self,
        chat_id: str,
        content: str,
        media_ids: Optional[list[dict]] = None,
        access_type: Optional[list[str]] = None,
        price: Optional[float] = None,
    ) -> SentMessage:
        """Send a message. Optionally attach PPV media.

        Args:
            chat_id: The chat groupId
            content: Message text (plain text, emojis OK, NO markdown)
            media_ids: List of {mediaId, previewId} dicts for attachments
            access_type: ["ppv"] and/or ["subscription", "follow", "list", "limited_time"]
            price: Dollar amount for PPV (only when access_type includes "ppv")
        """
        body = {"content": content}

        if media_ids:
            body["mediaIds"] = media_ids

        if access_type:
            body["access_type"] = access_type

        if price is not None:
            body["price"] = price

        data = self._request(
            "POST",
            f"/{self.config.account_id}/chats/{chat_id}/messages",
            json=body,
        )

        msg = data["data"]["data"]["response"]
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
        """Convenience: send a PPV message with locked media."""
        media_entry = {"mediaId": media_id}
        if preview_id:
            media_entry["previewId"] = preview_id

        return self.send_message(
            chat_id=chat_id,
            content=content,
            media_ids=[media_entry],
            access_type=["ppv"],
            price=price,
        )

    def like_message(self, chat_id: str, message_id: str) -> bool:
        """Like a message in a chat."""
        data = self._request(
            "POST",
            f"/{self.config.account_id}/chats/{chat_id}/messages/{message_id}/like",
        )
        return data.get("statusCode") == 200

    # ─── EARNINGS ────────────────────────────────────────

    def get_earnings(self) -> dict:
        """Get pending balance."""
        data = self._request("GET", f"/{self.config.account_id}/earnings")
        return data["data"]["data"]["response"]

    def get_fan_earnings(self, fan_id: str) -> list[dict]:
        """Get per-fan earnings breakdown (monthly)."""
        data = self._request(
            "GET", f"/{self.config.account_id}/earnings/fans/{fan_id}"
        )
        return data["data"]["data"]["response"]

    # ─── MEDIA ───────────────────────────────────────────

    def upload_media(self, file_path: str) -> str:
        """Upload a file, poll until complete, return mediaId."""
        # Step 1: Initiate upload
        with open(file_path, "rb") as f:
            # Use a raw httpx call for multipart
            self._rate_limit_wait()
            response = httpx.post(
                f"{self.config.base_url}/{self.config.account_id}/media/upload",
                headers={"x-api-key": self.config.api_key},
                files={"file": f},
                timeout=120.0,
            )
            response.raise_for_status()
            job_data = response.json()

        job_id = job_data["data"]["jobId"]
        logger.info(f"Upload job {job_id} queued for {file_path}")

        # Step 2: Poll until complete
        media_id = None
        for _ in range(30):  # max 60s of polling
            time.sleep(2)
            status_data = self._request("GET", f"/media/upload/{job_id}/status")
            state = status_data["data"].get("state", "")
            if state == "completed":
                media_id = status_data["data"]["result"]["mediaId"]
                logger.info(f"Upload complete: mediaId={media_id}")
                break
            elif state == "failed":
                raise Exception(f"Upload job {job_id} failed")
            logger.debug(f"Upload job {job_id} state: {state}")

        if not media_id:
            raise TimeoutError(f"Upload job {job_id} did not complete in time")

        return media_id

    def download_media(self, cdn_url: str) -> bytes:
        """Download media from Fansly CDN."""
        self._rate_limit_wait()
        response = httpx.post(
            f"{self.config.base_url}/media/download",
            headers={
                "x-api-key": self.config.api_key,
                "Content-Type": "application/json",
            },
            json={"cdnUrl": cdn_url},
            timeout=120.0,
        )
        response.raise_for_status()
        return response.content

    # ─── VAULT ───────────────────────────────────────────

    def list_albums(self) -> list[dict]:
        """Get all vault albums."""
        data = self._request("GET", f"/{self.config.account_id}/vault/albums")
        return data["data"]["data"]["response"].get("albums", [])

    def get_album_media(self, album_id: str, cursor: Optional[str] = None) -> tuple[list[dict], Optional[str]]:
        """Get media from a vault album."""
        params = {}
        if cursor:
            params["cursor"] = cursor
        data = self._request(
            "GET",
            f"/{self.config.account_id}/vault/albums/{album_id}/media",
            params=params,
        )
        response = data["data"]["data"]["response"]
        return response if isinstance(response, list) else response.get("media", []), data["data"]["data"].get("cursor")

    # ─── ANALYTICS ───────────────────────────────────────

    def get_profile_stats(
        self,
        before_date: Optional[int] = None,
        after_date: Optional[int] = None,
        period: int = 86400000,  # 1 day in ms
    ) -> dict:
        """Get profile analytics."""
        params = {"period": period}
        if before_date:
            params["beforeDate"] = before_date
        if after_date:
            params["afterDate"] = after_date
        data = self._request(
            "GET",
            f"/{self.config.account_id}/analytics/profilestats",
            params=params,
        )
        return data["data"]["data"]["response"]

    # ─── CLOSE ───────────────────────────────────────────

    def close(self):
        """Close the HTTP client."""
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
