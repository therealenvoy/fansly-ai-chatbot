"""Safe APIFansly creator onboarding and connection persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
import secrets
import threading
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ..apifansly_client import (
    ApifanslyAccountConnector,
    ApifanslyClient,
    ApifanslyConfig,
)
from ..persistence.schema import (
    CREATOR_CONNECTIONS,
    CREATOR_SETTINGS,
    CREATORS,
    utcnow,
)


CREATOR_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}[a-z0-9]$")
COUNTRY_CODE_PATTERN = re.compile(r"^[A-Z]{2}$")


class CreatorConnectionError(ValueError):
    """Privacy-safe creator connection error."""


def _creator_id(label: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")
    normalized = normalized[:63].strip("_")
    if len(normalized) < 3 or not CREATOR_ID_PATTERN.fullmatch(normalized):
        raise CreatorConnectionError(
            "Model name must contain at least three letters or numbers"
        )
    return normalized


def _profile(response: dict[str, Any]) -> dict[str, str | None]:
    account = response.get("account", response)
    if not isinstance(account, dict):
        account = {}
    avatar = account.get("avatar")
    if isinstance(avatar, dict):
        avatar = avatar.get("url") or avatar.get("location")
    return {
        "native_account_id": str(account.get("id") or "").strip() or None,
        "display_name": str(
            account.get("displayName")
            or account.get("display_name")
            or account.get("username")
            or "Fansly model"
        ).strip(),
        "username": str(account.get("username") or "").strip() or None,
        "avatar_url": str(avatar or account.get("avatarUrl") or "").strip() or None,
    }


class CreatorConnectionRepository:
    def __init__(self, engine):
        self.engine = engine

    def _insert(self, table):
        if self.engine.dialect.name == "postgresql":
            return pg_insert(table)
        if self.engine.dialect.name == "sqlite":
            return sqlite_insert(table)
        return insert(table)

    def ensure_legacy(
        self,
        creator_id: str,
        provider_account_id: str,
        *,
        display_name: str,
    ) -> None:
        if not provider_account_id.strip():
            return
        now = utcnow()
        with self.engine.begin() as connection:
            creator = self._insert(CREATORS).values(
                id=creator_id,
                created_at=now,
                updated_at=now,
            )
            if hasattr(creator, "on_conflict_do_nothing"):
                creator = creator.on_conflict_do_nothing(index_elements=["id"])
            connection.execute(creator)
            row = self._insert(CREATOR_CONNECTIONS).values(
                creator_id=creator_id,
                provider="apifansly",
                provider_account_id=provider_account_id.strip(),
                display_name=display_name,
                status="connected",
                created_at=now,
                updated_at=now,
            )
            if hasattr(row, "on_conflict_do_nothing"):
                row = row.on_conflict_do_nothing(index_elements=["creator_id"])
            connection.execute(row)

    def upsert(
        self,
        *,
        creator_id: str,
        provider_account_id: str,
        country_code: str,
        profile: dict[str, str | None],
    ) -> None:
        now = utcnow()
        with self.engine.begin() as connection:
            creator = self._insert(CREATORS).values(
                id=creator_id,
                created_at=now,
                updated_at=now,
            )
            if hasattr(creator, "on_conflict_do_update"):
                creator = creator.on_conflict_do_update(
                    index_elements=["id"],
                    set_={"updated_at": now},
                )
            connection.execute(creator)
            values = {
                "creator_id": creator_id,
                "provider": "apifansly",
                "provider_account_id": provider_account_id,
                "native_account_id": profile["native_account_id"],
                "display_name": profile["display_name"] or creator_id,
                "username": profile["username"],
                "avatar_url": profile["avatar_url"],
                "country_code": country_code,
                "status": "connected",
                "last_verified_at": now,
                "created_at": now,
                "updated_at": now,
            }
            statement = self._insert(CREATOR_CONNECTIONS).values(**values)
            if hasattr(statement, "on_conflict_do_update"):
                statement = statement.on_conflict_do_update(
                    index_elements=["creator_id"],
                    set_={key: value for key, value in values.items() if key not in {"creator_id", "created_at"}},
                )
            connection.execute(statement)
            disabled = self._insert(CREATOR_SETTINGS).values(
                creator_id=creator_id,
                key="bot_enabled",
                value="false",
                updated_at=now,
            )
            if hasattr(disabled, "on_conflict_do_nothing"):
                disabled = disabled.on_conflict_do_nothing(
                    index_elements=["creator_id", "key"]
                )
            connection.execute(disabled)

    def list_public(self) -> list[dict[str, Any]]:
        statement = select(
            CREATOR_CONNECTIONS.c.creator_id,
            CREATOR_CONNECTIONS.c.display_name,
            CREATOR_CONNECTIONS.c.username,
            CREATOR_CONNECTIONS.c.avatar_url,
            CREATOR_CONNECTIONS.c.status,
            CREATOR_CONNECTIONS.c.last_verified_at,
        ).order_by(CREATOR_CONNECTIONS.c.created_at)
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [dict(row) for row in rows]

    def provider_account_id(self, creator_id: str) -> str | None:
        statement = select(
            CREATOR_CONNECTIONS.c.provider_account_id
        ).where(
            CREATOR_CONNECTIONS.c.creator_id == creator_id,
            CREATOR_CONNECTIONS.c.status == "connected",
        )
        with self.engine.connect() as connection:
            value = connection.execute(statement).scalar_one_or_none()
        return str(value) if value else None

    def contains(self, creator_id: str) -> bool:
        return self.provider_account_id(creator_id) is not None


@dataclass
class _Pending:
    username: str
    password: str
    label: str
    country_code: str
    two_factor_token: str
    expires_at: datetime
    attempts: int = 0


class PendingConnectionStore:
    """Short-lived, process-local 2FA handoff; nothing is persisted."""

    def __init__(self, ttl: timedelta = timedelta(minutes=10)):
        self.ttl = ttl
        self._items: dict[str, _Pending] = {}
        self._lock = threading.Lock()

    def put(self, **values: str) -> str:
        nonce = secrets.token_urlsafe(32)
        pending = _Pending(
            **values,
            expires_at=datetime.now(timezone.utc) + self.ttl,
        )
        with self._lock:
            self._purge()
            self._items[nonce] = pending
        return nonce

    def get(self, nonce: str) -> _Pending:
        with self._lock:
            self._purge()
            pending = self._items.get(nonce)
            if pending is not None:
                pending.attempts += 1
                if pending.attempts > 3:
                    self._items.pop(nonce, None)
                    pending = None
        if pending is None:
            raise CreatorConnectionError(
                "The verification attempt expired; connect the model again"
            )
        return pending

    def discard(self, nonce: str) -> None:
        with self._lock:
            self._items.pop(nonce, None)

    def _purge(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [
            key for key, value in self._items.items()
            if value.expires_at <= now
        ]
        for key in expired:
            self._items.pop(key, None)


class CreatorConnectionService:
    def __init__(
        self,
        repository: CreatorConnectionRepository,
        *,
        api_key: str,
        webhook_token: str = "",
        pending: PendingConnectionStore | None = None,
    ):
        self.repository = repository
        self.api_key = api_key.strip()
        self.webhook_token = webhook_token.strip()
        self.pending = pending or PendingConnectionStore()
        self.connector = ApifanslyAccountConnector(api_key=self.api_key)
        self._clients: dict[str, ApifanslyClient] = {}
        self._lock = threading.Lock()

    def list_public(self) -> list[dict[str, Any]]:
        return self.repository.list_public()

    def connect(
        self,
        *,
        username: str,
        password: str,
        label: str,
        country_code: str,
    ) -> dict[str, Any]:
        self._validate(username, password, label, country_code)
        if self.repository.contains(_creator_id(label)):
            raise CreatorConnectionError(
                "That model name is already connected"
            )
        result = self.connector.connect(
            username=username.strip(),
            password=password,
            name=label.strip(),
            country_code=country_code,
        )
        if result.get("requires_2fa"):
            token = str(result.get("twofa_token") or "")
            if not token:
                raise CreatorConnectionError(
                    "APIFansly requested verification without a valid token"
                )
            attempt = self.pending.put(
                username=username.strip(),
                password=password,
                label=label.strip(),
                country_code=country_code,
                two_factor_token=token,
            )
            return {
                "requires_2fa": True,
                "attempt": attempt,
                "masked_email": str(result.get("masked_email") or ""),
            }
        return self._complete(result, label, country_code)

    def verify_2fa(self, *, attempt: str, code: str) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9]{4,10}", code.strip()):
            raise CreatorConnectionError("Enter the verification code")
        pending = self.pending.get(attempt)
        result = self.connector.verify_2fa(
            username=pending.username,
            password=pending.password,
            two_factor_token=pending.two_factor_token,
            two_factor_code=code.strip(),
            name=pending.label,
            country_code=pending.country_code,
        )
        self.pending.discard(attempt)
        return self._complete(
            result,
            pending.label,
            pending.country_code,
        )

    def client_for(self, creator_id: str) -> ApifanslyClient | None:
        account_id = self.repository.provider_account_id(creator_id)
        if not account_id or not self.api_key:
            return None
        with self._lock:
            client = self._clients.get(creator_id)
            if client is None or client.account_id != account_id:
                client = ApifanslyClient(
                    ApifanslyConfig(
                        api_key=self.api_key,
                        account_id=account_id,
                        webhook_token=self.webhook_token,
                    )
                )
                self._clients[creator_id] = client
        return client

    def _complete(
        self,
        result: dict[str, Any],
        label: str,
        country_code: str,
    ) -> dict[str, Any]:
        account_id = str(
            result.get("account_id")
            or result.get("accountId")
            or ""
        ).strip()
        if not account_id:
            raise CreatorConnectionError(
                "APIFansly did not return a connected account"
            )
        creator_id = _creator_id(label)
        client = ApifanslyClient(
            ApifanslyConfig(
                api_key=self.api_key,
                account_id=account_id,
                webhook_token=self.webhook_token,
            )
        )
        profile = _profile(client.current_account())
        self.repository.upsert(
            creator_id=creator_id,
            provider_account_id=account_id,
            country_code=country_code,
            profile=profile,
        )
        with self._lock:
            self._clients[creator_id] = client
        return {
            "requires_2fa": False,
            "model": {
                "creator_id": creator_id,
                "display_name": profile["display_name"],
                "username": profile["username"],
                "avatar_url": profile["avatar_url"],
                "status": "connected",
            },
        }

    def _validate(
        self,
        username: str,
        password: str,
        label: str,
        country_code: str,
    ) -> None:
        if not self.api_key:
            raise CreatorConnectionError("APIFansly is not configured")
        if not 3 <= len(username.strip()) <= 255:
            raise CreatorConnectionError("Enter the Fansly login")
        if not 8 <= len(password) <= 512:
            raise CreatorConnectionError("Enter the Fansly password")
        _creator_id(label)
        if not COUNTRY_CODE_PATTERN.fullmatch(country_code):
            raise CreatorConnectionError("Choose a two-letter country code")
