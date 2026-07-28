"""Fansly API Client — OnlyFansAPI's Fansly product (app.onlyfansapi.com).

Base URL: https://app.onlyfansapi.com
Auth: Authorization: Bearer <token>
Docs: https://docs.onlyfansapi.com/api-reference/fansly (closed beta)

Confirmed gaps in this closed beta: no vault/album endpoints, no documented
paid-message fields, and wallet transactions have no fan/message attribution.
Unsupported operations fail closed rather than fabricating provider behavior.
"""

import logging
import time
from typing import Any, Optional

import httpx

from .provider_credit import ProviderCreditGovernor
from .fansly_client import (
    FanslyApiClient,
    ChatInfo,
    MessageInfo,
    SentMessage,
    AuthError,
    PaymentRequiredError,
    NotFoundError,
    ProviderRequestError,
    ProviderDeliveryUnknownError,
    ProviderCapabilities,
    UnsupportedProviderFeature,
    UserPresence,
    WalletTransaction,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://app.onlyfansapi.com"


class FanslyApiClientImpl(FanslyApiClient):
    """HTTP client for OnlyFansAPI's Fansly product."""

    def __init__(
        self,
        api_key: str,
        timeout: float = 30.0,
        *,
        credit_governor: ProviderCreditGovernor | None = None,
    ):
        self.api_key = api_key.strip()
        self.timeout = timeout
        self.credit_governor = credit_governor
        self._account_id: Optional[str] = None
        self._creator_fansly_id: Optional[str] = None
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        self.client = httpx.Client(
            base_url=BASE_URL,
            headers=headers,
            timeout=timeout,
        )

    @property
    def provider_name(self) -> str:
        return "OnlyFansAPI Fansly"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_free_media_messages=True,
            supports_paid_messages=False,
            supports_attributed_purchases=False,
            supports_wallet_transactions=True,
            supports_vault_albums=False,
            supports_user_presence=True,
        )

    @property
    def account_id(self) -> str:
        if self._account_id is None:
            self._resolve_account_id()
        return self._account_id

    @property
    def creator_fansly_id(self) -> str:
        """Numeric Fansly creator ID used by message ``senderId`` fields."""
        if self._creator_fansly_id is None:
            self._resolve_account_id()
        return self._creator_fansly_id

    def _resolve_account_id(self):
        if not self.api_key:
            raise AuthError("FANSLY_API_KEY is not configured")
        data = self._request(
            "GET",
            "/api/fansly/accounts",
            operation="accounts.verify",
            request_class="control",
            expected_credits=0,
            allow_when_open=True,
        )
        accounts = data if isinstance(data, list) else []
        if not accounts:
            raise AuthError("No connected Fansly account found on this API key")
        account = accounts[0]
        creator_fansly_id = (
            account.get("fansly_id")
            or account.get("fansly_user_data", {}).get("id")
        )
        if not creator_fansly_id:
            raise AuthError(
                "Connected Fansly account does not expose a numeric fansly_id"
            )
        self._account_id = account["id"]
        self._creator_fansly_id = str(creator_fansly_id)

    def verify_auth(self) -> bool:
        """Resolve and cache the connected account id — also proves the key works."""
        self._resolve_account_id()
        return True

    def attach_credit_governor(
        self,
        governor: ProviderCreditGovernor,
    ) -> None:
        self.credit_governor = governor

    @staticmethod
    def _credit_meta(payload: Any) -> tuple[int | None, int | None]:
        if not isinstance(payload, dict):
            return None, None
        meta = payload.get("_meta")
        credits = meta.get("_credits") if isinstance(meta, dict) else None
        used = credits.get("used") if isinstance(credits, dict) else None
        balance = (
            credits.get("balance") if isinstance(credits, dict) else None
        )
        if used is None and payload.get("credits_used") is not None:
            used = payload.get("credits_used")
        try:
            normalized_used = int(used) if used is not None else None
        except (TypeError, ValueError):
            normalized_used = None
        try:
            normalized_balance = (
                int(balance) if balance is not None else None
            )
        except (TypeError, ValueError):
            normalized_balance = None
        return normalized_used, normalized_balance

    def _reserve(
        self,
        operation: str,
        *,
        request_class: str,
        expected_credits: int,
        allow_when_open: bool,
    ):
        if self.credit_governor is None:
            return None
        return self.credit_governor.reserve(
            operation,
            request_class=request_class,
            credits=expected_credits,
            allow_when_open=allow_when_open,
        )

    def _finalize(
        self,
        reservation,
        *,
        method: str,
        result: str,
        status_code: int | None,
        payload: Any = None,
        known_used_credits: int | None = None,
        retry_count: int = 0,
        detail_code: str | None = None,
    ) -> None:
        if reservation is None or self.credit_governor is None:
            return
        used, balance = self._credit_meta(payload)
        if known_used_credits is not None:
            used = known_used_credits
        self.credit_governor.finalize(
            reservation,
            method=method,
            result=result,
            status_code=status_code,
            used_credits=used,
            balance=balance,
            retry_count=retry_count,
            detail_code=detail_code,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        operation: str = "provider.request",
        request_class: str = "read",
        expected_credits: int = 1,
        allow_when_open: bool = False,
        **kwargs,
    ) -> dict | list:
        method = method.upper()
        retry_safe = method in {"GET", "HEAD"}
        for attempt in range(2):
            reservation = self._reserve(
                operation,
                request_class=request_class,
                expected_credits=expected_credits,
                allow_when_open=allow_when_open,
            )
            try:
                response = self.client.request(method, path, **kwargs)
            except (httpx.TimeoutException, httpx.TransportError) as error:
                self._finalize(
                    reservation,
                    method=method,
                    result="transport_error",
                    status_code=None,
                    retry_count=attempt,
                    detail_code=type(error).__name__,
                )
                if retry_safe and attempt == 0:
                    continue
                if not retry_safe:
                    raise ProviderDeliveryUnknownError(
                        f"{operation} delivery outcome is unknown"
                    ) from error
                raise ProviderRequestError(
                    f"{operation} failed after a bounded retry"
                ) from error

            payload = None
            try:
                payload = response.json()
            except (ValueError, TypeError):
                payload = None
            status = int(response.status_code)

            if status == 402:
                self._finalize(
                    reservation,
                    method=method,
                    result="payment_required",
                    status_code=status,
                    payload=payload,
                    known_used_credits=0,
                    retry_count=attempt,
                    detail_code="payment_required",
                )
                if self.credit_governor is not None:
                    self.credit_governor.open_circuit("payment_required")
                raise PaymentRequiredError(
                    f"{operation} blocked because provider credits are unavailable"
                )
            if status in (401, 403):
                self._finalize(
                    reservation,
                    method=method,
                    result="auth_error",
                    status_code=status,
                    payload=payload,
                    retry_count=attempt,
                    detail_code=f"http_{status}",
                )
                raise AuthError(
                    f"{operation} authentication failed with HTTP {status}"
                )
            if status == 404:
                self._finalize(
                    reservation,
                    method=method,
                    result="not_found",
                    status_code=status,
                    payload=payload,
                    retry_count=attempt,
                    detail_code="http_404",
                )
                raise NotFoundError(f"{operation} resource was not found")
            if status == 429 or 500 <= status <= 599:
                self._finalize(
                    reservation,
                    method=method,
                    result="retryable_error",
                    status_code=status,
                    payload=payload,
                    retry_count=attempt,
                    detail_code=f"http_{status}",
                )
                if retry_safe and attempt == 0:
                    if status == 429:
                        try:
                            delay = float(
                                response.headers.get("Retry-After", "0")
                            )
                        except (TypeError, ValueError):
                            delay = 0
                        time.sleep(min(max(delay, 0), 5))
                    continue
                raise ProviderRequestError(
                    f"{operation} failed with HTTP {status}"
                )
            if status >= 400:
                self._finalize(
                    reservation,
                    method=method,
                    result="request_error",
                    status_code=status,
                    payload=payload,
                    retry_count=attempt,
                    detail_code=f"http_{status}",
                )
                raise ProviderRequestError(
                    f"{operation} failed with HTTP {status}"
                )

            self._finalize(
                reservation,
                method=method,
                result="success",
                status_code=status,
                payload=payload,
                retry_count=attempt,
            )
            if payload is None:
                raise ProviderRequestError(
                    f"{operation} returned an invalid JSON response"
                )
            return payload
        raise ProviderRequestError(f"{operation} failed")

    def list_fansly_webhooks(self) -> list[dict]:
        """Return provider webhook registrations through a zero-credit control call."""
        payload = self._request(
            "GET",
            "/api/webhooks",
            operation="webhooks.list",
            request_class="control",
            expected_credits=0,
        )
        rows = payload.get("data", []) if isinstance(payload, dict) else payload
        return [row for row in rows if isinstance(row, dict)]

    def list_available_webhook_events(self) -> dict:
        """Return the live Fansly event catalog and reported credit use."""
        payload = self._request(
            "GET",
            "/api/webhooks/events",
            operation="webhooks.events",
            request_class="control",
            expected_credits=0,
        )
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        events = [
            {
                "value": str(row.get("value") or ""),
                "description": str(row.get("description") or ""),
            }
            for row in rows
            if isinstance(row, dict) and row.get("value")
        ]
        used, _ = self._credit_meta(payload)
        return {"events": events, "credits_used": used}

    def ensure_fansly_webhook(
        self,
        endpoint_url: str,
        signing_secret: str,
        event_names: list[str] | tuple[str, ...],
    ) -> dict:
        """Create or reconcile the signed, account-scoped Fansly webhook."""
        endpoint_url = endpoint_url.strip()
        signing_secret = signing_secret.strip()
        events = sorted(
            {
                str(event_name).strip()
                for event_name in event_names
                if str(event_name).strip()
            }
        )
        if not endpoint_url.startswith("https://"):
            raise ValueError("Webhook endpoint must use HTTPS")
        if len(signing_secret) < 32:
            raise ValueError("Webhook signing secret must be at least 32 characters")
        if not events or any(
            not event_name.startswith("fansly.")
            for event_name in events
        ):
            raise ValueError("Webhook events must be non-empty Fansly events")

        matching = [
            row
            for row in self.list_fansly_webhooks()
            if str(
                row.get("url") or row.get("endpoint_url") or ""
            ).strip()
            == endpoint_url
        ]
        if len(matching) > 1:
            raise UnsupportedProviderFeature(
                "Multiple webhooks already use the owned endpoint; "
                "refusing ambiguous reconciliation"
            )
        existing = matching[0] if matching else None
        if existing is not None and not existing.get("has_signing_secret"):
            raise UnsupportedProviderFeature(
                "The production webhook endpoint already exists without a signing secret; "
                "refusing to enable or replace it automatically"
            )

        if existing is None:
            created = self._request(
                "POST",
                "/api/webhooks",
                operation="webhooks.create",
                request_class="control",
                json={
                    "endpoint_url": endpoint_url,
                    "signing_secret": signing_secret,
                    "events": events,
                    "account_scope": "inclusive",
                    "account_ids": [self.account_id],
                },
                expected_credits=0,
            )
            existing = created.get("data", {})
            if not existing.get("has_signing_secret"):
                raise UnsupportedProviderFeature(
                    "OnlyFansAPI did not confirm a signing secret on the new webhook"
                )

        webhook_id = str(existing.get("id") or "").strip()
        if not webhook_id:
            raise UnsupportedProviderFeature(
                "OnlyFansAPI webhook response did not contain an id"
            )
        updated = self._request(
            "PUT",
            f"/api/webhooks/{webhook_id}",
            operation="webhooks.update",
            request_class="control",
            json={
                "endpoint_url": endpoint_url,
                "events": events,
                "enabled": True,
                "account_scope": "inclusive",
                "account_ids": [self.account_id],
            },
            expected_credits=0,
        )
        result = updated.get("data", {})
        if not result.get("enabled"):
            raise UnsupportedProviderFeature(
                "OnlyFansAPI did not confirm that the Fansly webhook is enabled"
            )
        returned_url = str(
            result.get("url") or result.get("endpoint_url") or ""
        ).strip()
        if returned_url and returned_url != endpoint_url:
            raise UnsupportedProviderFeature(
                "OnlyFansAPI confirmed a different webhook endpoint"
            )
        if set(result.get("events") or []) != set(events):
            raise UnsupportedProviderFeature(
                "OnlyFansAPI did not confirm the requested event set"
            )
        if (
            result.get("account_scope") != "inclusive"
            or set(result.get("account_ids") or []) != {self.account_id}
        ):
            raise UnsupportedProviderFeature(
                "OnlyFansAPI did not confirm the requested account scope"
            )
        return result

    def pause_fansly_webhook(self, endpoint_url: str) -> dict:
        """Pause exactly one webhook owned by this endpoint; never delete it."""
        endpoint_url = endpoint_url.strip()
        matching = [
            row
            for row in self.list_fansly_webhooks()
            if str(
                row.get("url") or row.get("endpoint_url") or ""
            ).strip()
            == endpoint_url
        ]
        if len(matching) != 1:
            raise UnsupportedProviderFeature(
                "Expected exactly one webhook at the owned endpoint"
            )
        existing = matching[0]
        webhook_id = str(existing.get("id") or "").strip()
        if not webhook_id:
            raise UnsupportedProviderFeature(
                "OnlyFansAPI webhook response did not contain an id"
            )
        updated = self._request(
            "PUT",
            f"/api/webhooks/{webhook_id}",
            operation="webhooks.pause",
            request_class="control",
            expected_credits=0,
            json={
                "endpoint_url": endpoint_url,
                "events": list(existing.get("events") or []),
                "enabled": False,
                "account_scope": existing.get("account_scope", "inclusive"),
                "account_ids": list(existing.get("account_ids") or []),
            },
        )
        result = updated.get("data", {})
        if result.get("enabled") is not False:
            raise UnsupportedProviderFeature(
                "OnlyFansAPI did not confirm that the webhook is paused"
            )
        return result

    def ensure_message_webhook(
        self,
        endpoint_url: str,
        signing_secret: str,
    ) -> dict:
        """Backward-compatible one-event registration wrapper."""
        return self.ensure_fansly_webhook(
            endpoint_url,
            signing_secret,
            ["fansly.messages.received"],
        )

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
            operation="fansly.chats.list",
            request_class="read",
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

    def get_user_presence(
        self,
        fan_ids: list[str],
    ) -> list[UserPresence]:
        """Fetch documented bulk Fansly user details by numeric account ID."""
        normalized = list(
            dict.fromkeys(
                str(fan_id).strip()
                for fan_id in fan_ids
                if str(fan_id).strip()
            )
        )
        if not normalized:
            return []
        if len(normalized) > 100:
            raise ValueError("user presence lookup supports at most 100 IDs")
        data = self._request(
            "GET",
            f"/api/fansly/{self.account_id}/users/",
            operation="fansly.users.presence",
            request_class="optional_read",
            params={"ids": ",".join(normalized)},
        )
        rows = data.get("data", []) if isinstance(data, dict) else []
        return [
            UserPresence(
                fan_id=str(row["id"]),
                username=str(row.get("username") or ""),
                display_name=(
                    str(row["displayName"])
                    if row.get("displayName")
                    else None
                ),
                last_seen_at=(
                    float(row["lastSeenAt"])
                    if row.get("lastSeenAt") is not None
                    else None
                ),
                status_id=(
                    int(row["statusId"])
                    if row.get("statusId") is not None
                    else None
                ),
            )
            for row in rows
            if isinstance(row, dict) and row.get("id") is not None
        ]

    def list_messages(
        self, chat_id: str, limit: int = 10, cursor: Optional[str] = None
    ) -> tuple[list[MessageInfo], Optional[str]]:
        params = {"limit": limit}
        if cursor:
            params["before"] = cursor

        data = self._request(
            "GET",
            f"/api/fansly/{self.account_id}/chats/{chat_id}/messages",
            operation="fansly.messages.list",
            request_class="read",
            params=params,
        )
        inner = data.get("data", {})
        messages_raw = inner.get("messages", [])

        messages = []
        for msg in messages_raw:
            is_fan = str(msg.get("senderId", "")) != self.creator_fansly_id
            messages.append(MessageInfo(
                message_id=msg["id"],
                content=msg.get("content") or "",
                sender_id=msg["senderId"],
                created_at=msg.get("createdAt", 0),
                is_from_fan=is_fan,
                has_attachments=bool(msg.get("attachments")),
                total_tip=msg.get("totalTipAmount", 0),
                attachments=list(msg.get("attachments") or []),
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
            "POST",
            f"/api/fansly/{self.account_id}/chats/{chat_id}/messages",
            operation="fansly.messages.send",
            request_class="send",
            json=body,
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
            operation="fansly.wallet.list",
            request_class="read",
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
            operation="fansly.reactions.create",
            request_class="send",
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
                operation="fansly.media.upload",
                request_class="send",
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
