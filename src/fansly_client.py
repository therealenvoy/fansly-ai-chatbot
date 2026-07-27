"""Provider-neutral contract and typed records for Fansly integrations.

Concrete HTTP implementations are selected only through ``client_factory``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class FanslyClientError(Exception):
    """Base exception for Fansly provider failures."""


class PaymentRequiredError(FanslyClientError):
    """The configured provider account needs billing attention."""


class NotFoundError(FanslyClientError):
    """The requested provider resource does not exist."""


class AuthError(FanslyClientError):
    """Provider authentication or authorization failed."""


class UnsupportedProviderFeature(FanslyClientError):
    """The selected provider does not document the requested capability."""


@dataclass(frozen=True)
class ProviderCapabilities:
    supports_free_media_messages: bool = False
    supports_paid_messages: bool = False
    supports_attributed_purchases: bool = False
    supports_wallet_transactions: bool = False
    supports_vault_albums: bool = False
    supports_user_presence: bool = False


@dataclass(frozen=True)
class WalletTransaction:
    transaction_id: str
    transaction_type: int
    destination: str
    amount_millis: int
    destination_tax_millis: int
    new_balance_millis: int
    created_at: float
    status: int


@dataclass
class ChatInfo:
    chat_id: str
    partner_account_id: str
    partner_username: str
    partner_display_name: str
    unread_count: int = 0
    last_message_id: str | None = None
    last_unread_message_id: str | None = None
    subscription_tier_id: str | None = None
    avatar_url: str | None = None


@dataclass
class MessageInfo:
    message_id: str
    content: str
    sender_id: str
    created_at: float
    is_from_fan: bool
    has_attachments: bool = False
    total_tip: float = 0.0
    attachments: list[dict] = field(default_factory=list)


@dataclass
class SentMessage:
    message_id: str
    content: str
    created_at: float
    success: bool
    purchase_reference_id: str | None = None


@dataclass(frozen=True)
class UserPresence:
    """Provider observation used to derive recent online activity."""

    fan_id: str
    username: str
    display_name: str | None
    last_seen_at: float | None
    status_id: int | None = None


class FanslyApiClient(ABC):
    """Provider contract consumed by the bot."""

    @property
    def provider_name(self) -> str:
        return self.__class__.__name__

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()

    @property
    @abstractmethod
    def account_id(self) -> str: ...

    @abstractmethod
    def verify_auth(self) -> bool: ...

    @abstractmethod
    def list_chats_page(
        self,
        *,
        limit: int = 100,
        offset: int | str = 0,
        order: str = "newest",
    ) -> tuple[list[ChatInfo], int | str | None]: ...

    @abstractmethod
    def get_all_chats(
        self,
        filter_type: str = "all",
    ) -> list[ChatInfo]: ...

    @abstractmethod
    def list_messages(
        self,
        chat_id: str,
        limit: int = 10,
        cursor: str | None = None,
    ) -> tuple[list[MessageInfo], str | None]: ...

    @abstractmethod
    def send_message(
        self,
        chat_id: str,
        content: str,
        media_ids: list[dict] | None = None,
        access_type: list[str] | None = None,
        price: float | None = None,
    ) -> SentMessage: ...

    @abstractmethod
    def send_ppv(
        self,
        chat_id: str,
        content: str,
        media_id: str,
        price: float,
        preview_id: str | None = None,
    ) -> SentMessage: ...

    def get_user_presence(
        self,
        fan_ids: list[str],
    ) -> list[UserPresence]:
        raise UnsupportedProviderFeature(
            "configured provider does not expose user presence"
        )

    def list_wallet_transactions_page(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[WalletTransaction], int | None]:
        raise UnsupportedProviderFeature(
            "Wallet transactions are unavailable for this provider"
        )

    @abstractmethod
    def like_message(self, chat_id: str, message_id: str) -> bool: ...

    @abstractmethod
    def upload_media(self, file_path: str) -> str: ...

    @abstractmethod
    def list_albums(self) -> list[dict]: ...

    @abstractmethod
    def get_album_media(
        self,
        album_id: str,
        cursor: str | None = None,
    ) -> tuple[list[dict], str | None]: ...

    @abstractmethod
    def close(self) -> None: ...
