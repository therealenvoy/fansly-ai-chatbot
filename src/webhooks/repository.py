"""Atomic persistence for normalized provider webhook events."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Engine, case, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from src.persistence.schema import (
    CONVERSATIONS,
    FANS,
    FAN_MESSAGES,
    INBOUND_MESSAGES,
    PROVIDER_WEBHOOK_EVENTS,
)

from .onlyfansapi import OnlyFansApiFanslyMessage


@dataclass(frozen=True)
class WebhookIngestResult:
    created: bool
    inbound_message_id: int | None


class WebhookEventRepository:
    """Commit the event, CRM message, and inbound work as one transaction."""

    def __init__(self, engine: Engine):
        self.engine = engine

    def ingest_received(
        self,
        *,
        creator_id: str,
        event: OnlyFansApiFanslyMessage,
        available_at: datetime,
    ) -> WebhookIngestResult:
        now = datetime.now(timezone.utc)
        event_key = event.event_key or hashlib.sha256(
            "\0".join(
                (
                    event.event_name,
                    event.account_id,
                    event.platform_message_id,
                )
            ).encode("utf-8")
        ).hexdigest()
        with self.engine.begin() as connection:
            event_insert = self._insert(PROVIDER_WEBHOOK_EVENTS).values(
                creator_id=creator_id,
                event_key=event_key,
                provider_event_id=event.provider_event_id,
                event_name=event.event_name,
                schema_version=event.schema_version,
                platform_message_id=event.platform_message_id,
                chat_id=event.chat_id,
                direction="inbound",
                source_class="provider_webhook",
                status="accepted",
                error_category=None,
                provider_created_at=event.provider_created_at,
                received_at=now,
                processed_at=now,
            )
            event_insert = event_insert.on_conflict_do_nothing(
                index_elements=["creator_id", "event_key"]
            )
            if connection.execute(event_insert).rowcount != 1:
                return WebhookIngestResult(False, None)

            fan_insert = self._insert(FANS).values(
                creator_id=creator_id,
                fan_id=event.fan_id,
                display_name=event.display_name,
                username=event.username,
                avatar_url=None,
                created_at=now,
                updated_at=now,
            )
            fan_insert = fan_insert.on_conflict_do_update(
                index_elements=["creator_id", "fan_id"],
                set_={
                    "display_name": func.coalesce(
                        fan_insert.excluded.display_name,
                        FANS.c.display_name,
                    ),
                    "username": func.coalesce(
                        fan_insert.excluded.username,
                        FANS.c.username,
                    ),
                    "updated_at": now,
                },
            )
            connection.execute(fan_insert)

            conversation_insert = self._insert(CONVERSATIONS).values(
                creator_id=creator_id,
                chat_id=event.chat_id,
                fan_id=event.fan_id,
                provider_cursor=None,
                last_platform_message_id=event.platform_message_id,
                last_activity_at=event.provider_created_at,
                created_at=now,
                updated_at=now,
            )
            chat_changed = (
                CONVERSATIONS.c.chat_id
                != conversation_insert.excluded.chat_id
            )
            conversation_insert = conversation_insert.on_conflict_do_update(
                index_elements=["creator_id", "fan_id"],
                set_={
                    "chat_id": conversation_insert.excluded.chat_id,
                    "provider_cursor": case(
                        (chat_changed, None),
                        else_=CONVERSATIONS.c.provider_cursor,
                    ),
                    "last_platform_message_id": event.platform_message_id,
                    "last_activity_at": event.provider_created_at,
                    "updated_at": now,
                },
            )
            connection.execute(conversation_insert)

            existing_message = connection.execute(
                select(FAN_MESSAGES.c.id).where(
                    (FAN_MESSAGES.c.creator_id == creator_id)
                    & (
                        FAN_MESSAGES.c.message_id
                        == event.platform_message_id
                    )
                )
            ).first()
            if existing_message is None:
                connection.execute(
                    FAN_MESSAGES.insert().values(
                        fan_id=event.fan_id,
                        creator_id=creator_id,
                        chat_id=event.chat_id,
                        sender="fan",
                        content=event.content,
                        message_id=event.platform_message_id,
                        attachments=list(event.attachments),
                        created_at=event.provider_created_at,
                    )
                )

            inbound_insert = self._insert(INBOUND_MESSAGES).values(
                creator_id=creator_id,
                platform_message_id=event.platform_message_id,
                fan_id=event.fan_id,
                chat_id=event.chat_id,
                content=event.content,
                trigger_kind="unread",
                provider_created_at=event.provider_created_at,
                observed_at=now,
                available_at=available_at,
                status="pending",
                attempt_count=0,
            )
            inbound_insert = inbound_insert.on_conflict_do_nothing(
                index_elements=["creator_id", "platform_message_id"]
            )
            connection.execute(inbound_insert)
            inbound_id = connection.execute(
                select(INBOUND_MESSAGES.c.id).where(
                    (INBOUND_MESSAGES.c.creator_id == creator_id)
                    & (
                        INBOUND_MESSAGES.c.platform_message_id
                        == event.platform_message_id
                    )
                )
            ).scalar_one()
        return WebhookIngestResult(True, int(inbound_id))

    def record_dead_letter(
        self,
        *,
        creator_id: str,
        event_key: str,
        event_name: str,
        error_category: str,
    ) -> bool:
        """Store only normalized failure metadata, never the raw payload."""
        now = datetime.now(timezone.utc)
        statement = self._insert(PROVIDER_WEBHOOK_EVENTS).values(
            creator_id=creator_id,
            event_key=event_key[:64],
            provider_event_id=None,
            event_name=event_name[:96] or "unknown",
            schema_version=None,
            platform_message_id=None,
            chat_id=None,
            direction="unknown",
            source_class="provider_webhook",
            status="dead_letter",
            error_category=error_category[:64],
            provider_created_at=None,
            received_at=now,
            processed_at=None,
        )
        statement = statement.on_conflict_do_nothing(
            index_elements=["creator_id", "event_key"]
        )
        with self.engine.begin() as connection:
            return connection.execute(statement).rowcount == 1

    def _insert(self, table):
        if self.engine.dialect.name == "postgresql":
            return pg_insert(table)
        return sqlite_insert(table)
