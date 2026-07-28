"""Atomic persistence for normalized provider webhook events."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Engine, and_, case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from src.persistence.schema import (
    CONVERSATIONS,
    CONTACT_CLAIMS,
    CREATOR_SETTINGS,
    FANS,
    FAN_MESSAGES,
    INBOUND_MESSAGES,
    OUTBOX_MESSAGES,
    PROVIDER_ALERTS,
    PROVIDER_CIRCUIT_BREAKERS,
    PROVIDER_CONNECTION_STATES,
    PROVIDER_MESSAGE_STATES,
    PROVIDER_WEBHOOK_EVENTS,
)

from .onlyfansapi import (
    OnlyFansApiFanslyAccountEvent,
    OnlyFansApiFanslyDeletedMessage,
    OnlyFansApiFanslyMessage,
    OnlyFansApiFanslyReadReceipt,
    OnlyFansApiFanslySentMessage,
)


@dataclass(frozen=True)
class WebhookIngestResult:
    created: bool
    inbound_message_id: int | None
    canceled_count: int = 0
    quarantined: bool = False


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
                    event.provider_created_at.isoformat(),
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

            message_state = self._upsert_message_state(
                connection,
                creator_id=creator_id,
                platform_message_id=event.platform_message_id,
                chat_id=event.chat_id,
                fan_id=event.fan_id,
                direction="inbound",
                source_class="fan",
                provider_event_id=event.provider_event_id,
                provider_created_at=event.provider_created_at,
                now=now,
            )
            if message_state["deleted_at"] is not None:
                return WebhookIngestResult(True, None)

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
                last_speaker="fan",
                last_fan_message_at=event.provider_created_at,
                last_creator_message_at=None,
                last_read_at=None,
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
                    "last_platform_message_id": case(
                        (
                            or_(
                                CONVERSATIONS.c.last_activity_at.is_(None),
                                CONVERSATIONS.c.last_activity_at
                                <= event.provider_created_at,
                            ),
                            event.platform_message_id,
                        ),
                        else_=CONVERSATIONS.c.last_platform_message_id,
                    ),
                    "last_activity_at": case(
                        (
                            or_(
                                CONVERSATIONS.c.last_activity_at.is_(None),
                                CONVERSATIONS.c.last_activity_at
                                <= event.provider_created_at,
                            ),
                            event.provider_created_at,
                        ),
                        else_=CONVERSATIONS.c.last_activity_at,
                    ),
                    "last_speaker": case(
                        (
                            or_(
                                CONVERSATIONS.c.last_activity_at.is_(None),
                                CONVERSATIONS.c.last_activity_at
                                <= event.provider_created_at,
                            ),
                            "fan",
                        ),
                        else_=CONVERSATIONS.c.last_speaker,
                    ),
                    "last_fan_message_at": case(
                        (
                            or_(
                                CONVERSATIONS.c.last_fan_message_at.is_(None),
                                CONVERSATIONS.c.last_fan_message_at
                                <= event.provider_created_at,
                            ),
                            event.provider_created_at,
                        ),
                        else_=CONVERSATIONS.c.last_fan_message_at,
                    ),
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
                        source_class="fan",
                        provider_event_id=event.provider_event_id,
                        read_at=message_state["read_at"],
                        deleted_at=None,
                        created_at=event.provider_created_at,
                    )
                )

            latest_creator_message_at = connection.execute(
                select(
                    CONVERSATIONS.c.last_creator_message_at
                ).where(
                    and_(
                        CONVERSATIONS.c.creator_id == creator_id,
                        CONVERSATIONS.c.fan_id == event.fan_id,
                    )
                )
            ).scalar_one_or_none()
            if (
                latest_creator_message_at is not None
                and self._as_utc(latest_creator_message_at)
                >= self._as_utc(event.provider_created_at)
            ):
                return WebhookIngestResult(True, None)

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

    def ingest_sent(
        self,
        *,
        creator_id: str,
        event: OnlyFansApiFanslySentMessage,
    ) -> WebhookIngestResult:
        """Project a creator-authored message and invalidate stale work."""
        now = datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            if not self._insert_event(
                connection,
                creator_id=creator_id,
                event=event,
                platform_message_id=event.platform_message_id,
                chat_id=event.chat_id,
                direction="outbound",
            ):
                return WebhookIngestResult(False, None)

            matched_outbox = connection.execute(
                select(OUTBOX_MESSAGES).where(
                    and_(
                        OUTBOX_MESSAGES.c.creator_id == creator_id,
                        OUTBOX_MESSAGES.c.provider_message_id
                        == event.platform_message_id,
                    )
                )
            ).mappings().first()
            source_class = self._sent_source_class(
                event,
                matched_outbox,
            )
            fan_id = self._resolve_fan_id(
                connection,
                creator_id=creator_id,
                chat_id=event.chat_id,
                supplied_fan_id=event.fan_id,
            )
            if not fan_id:
                connection.execute(
                    update(PROVIDER_WEBHOOK_EVENTS)
                    .where(
                        and_(
                            PROVIDER_WEBHOOK_EVENTS.c.creator_id
                            == creator_id,
                            PROVIDER_WEBHOOK_EVENTS.c.event_key
                            == event.event_key,
                        )
                    )
                    .values(
                        status="dead_letter",
                        error_category="unknown_conversation",
                        processed_at=None,
                    )
                )
                return WebhookIngestResult(
                    True,
                    None,
                    quarantined=True,
                )

            self._ensure_fan(
                connection,
                creator_id=creator_id,
                fan_id=fan_id,
                now=now,
            )
            message_state = self._upsert_message_state(
                connection,
                creator_id=creator_id,
                platform_message_id=event.platform_message_id,
                chat_id=event.chat_id,
                fan_id=fan_id,
                direction="outbound",
                source_class=source_class,
                provider_event_id=event.provider_event_id,
                provider_created_at=event.provider_created_at,
                now=now,
            )
            self._upsert_conversation_activity(
                connection,
                creator_id=creator_id,
                fan_id=fan_id,
                chat_id=event.chat_id,
                platform_message_id=event.platform_message_id,
                speaker="creator",
                provider_created_at=event.provider_created_at,
                now=now,
            )

            existing_message = connection.execute(
                select(FAN_MESSAGES).where(
                    and_(
                        FAN_MESSAGES.c.creator_id == creator_id,
                        FAN_MESSAGES.c.message_id
                        == event.platform_message_id,
                    )
                )
            ).mappings().first()
            if existing_message is None:
                connection.execute(
                    FAN_MESSAGES.insert().values(
                        fan_id=fan_id,
                        creator_id=creator_id,
                        chat_id=event.chat_id,
                        sender="creator",
                        content=(
                            ""
                            if message_state["deleted_at"] is not None
                            else event.content
                        ),
                        message_id=event.platform_message_id,
                        attachments=(
                            []
                            if message_state["deleted_at"] is not None
                            else list(event.attachments)
                        ),
                        source_class=source_class,
                        provider_event_id=event.provider_event_id,
                        read_at=message_state["read_at"],
                        deleted_at=message_state["deleted_at"],
                        created_at=event.provider_created_at,
                    )
                )
            else:
                connection.execute(
                    update(FAN_MESSAGES)
                    .where(FAN_MESSAGES.c.id == existing_message["id"])
                    .values(
                        source_class=source_class,
                        provider_event_id=(
                            event.provider_event_id
                            or existing_message["provider_event_id"]
                        ),
                    )
                )

            matched_inbound_id = None
            matched_outbox_id = None
            if matched_outbox is not None:
                matched_outbox_id = int(matched_outbox["id"])
                matched_inbound_id = int(
                    matched_outbox["inbound_message_id"]
                )
                connection.execute(
                    update(OUTBOX_MESSAGES)
                    .where(
                        OUTBOX_MESSAGES.c.id == matched_outbox_id
                    )
                    .values(
                        status="sent",
                        sent_at=event.provider_created_at,
                        last_error=None,
                    )
                )

            pending_outboxes = connection.execute(
                select(
                    OUTBOX_MESSAGES.c.id,
                    OUTBOX_MESSAGES.c.inbound_message_id,
                ).where(
                    and_(
                        OUTBOX_MESSAGES.c.creator_id == creator_id,
                        OUTBOX_MESSAGES.c.fan_id == fan_id,
                        OUTBOX_MESSAGES.c.status == "pending",
                        (
                            OUTBOX_MESSAGES.c.id != matched_outbox_id
                            if matched_outbox_id is not None
                            else True
                        ),
                    )
                )
            ).all()
            canceled_outbox_ids = [int(row.id) for row in pending_outboxes]
            if canceled_outbox_ids:
                connection.execute(
                    update(OUTBOX_MESSAGES)
                    .where(
                        OUTBOX_MESSAGES.c.id.in_(canceled_outbox_ids)
                    )
                    .values(
                        status="cancelled_stale",
                        permit_status="revoked",
                        last_error="superseded by creator message",
                    )
                )

            inbound_filter = and_(
                INBOUND_MESSAGES.c.creator_id == creator_id,
                INBOUND_MESSAGES.c.fan_id == fan_id,
                INBOUND_MESSAGES.c.status.in_(
                    ("pending", "processing")
                ),
                INBOUND_MESSAGES.c.provider_created_at
                <= event.provider_created_at,
            )
            canceled_inbound = connection.execute(
                update(INBOUND_MESSAGES)
                .where(inbound_filter)
                .values(
                    status="completed",
                    completed_at=now,
                    locked_at=None,
                    last_error="superseded by creator message",
                )
            ).rowcount
            if matched_inbound_id is not None:
                connection.execute(
                    update(INBOUND_MESSAGES)
                    .where(
                        INBOUND_MESSAGES.c.id == matched_inbound_id
                    )
                    .values(
                        status="completed",
                        completed_at=now,
                        locked_at=None,
                        last_error=None,
                    )
                )

            connection.execute(
                update(CONTACT_CLAIMS)
                .where(
                    and_(
                        CONTACT_CLAIMS.c.creator_id == creator_id,
                        CONTACT_CLAIMS.c.fan_id == fan_id,
                        CONTACT_CLAIMS.c.status == "claimed",
                        (
                            or_(
                                CONTACT_CLAIMS.c.outbox_id.is_(None),
                                CONTACT_CLAIMS.c.outbox_id
                                != matched_outbox_id,
                            )
                            if matched_outbox_id is not None
                            else True
                        ),
                    )
                )
                .values(
                    status="cancelled",
                    denial_reason="creator_message_observed",
                )
            )
            claim_key = hashlib.sha256(
                f"provider-sent\0{event.event_key}".encode("utf-8")
            ).hexdigest()
            claim = self._insert(CONTACT_CLAIMS).values(
                creator_id=creator_id,
                fan_id=fan_id,
                trigger_type="provider_sent",
                trigger_event_id=event.platform_message_id,
                source_system=source_class,
                campaign_or_automation_id=(
                    event.automation_id or event.integration_id
                ),
                idempotency_key=claim_key,
                claimed_at=event.provider_created_at,
                cooldown_until=None,
                outbox_id=matched_outbox_id,
                native_message_hash=None,
                status="observed",
                denial_reason=None,
            )
            claim = claim.on_conflict_do_nothing(
                index_elements=["creator_id", "idempotency_key"]
            )
            connection.execute(claim)
        return WebhookIngestResult(
            True,
            None,
            canceled_count=(
                len(canceled_outbox_ids) + int(canceled_inbound or 0)
            ),
        )

    def ingest_deleted(
        self,
        *,
        creator_id: str,
        event: OnlyFansApiFanslyDeletedMessage,
    ) -> WebhookIngestResult:
        """Tombstone deleted content and cancel its sole pending answer."""
        now = datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            if not self._insert_event(
                connection,
                creator_id=creator_id,
                event=event,
                platform_message_id=event.platform_message_id,
                chat_id=event.chat_id,
                direction="unknown",
            ):
                return WebhookIngestResult(False, None)
            existing_state = connection.execute(
                select(PROVIDER_MESSAGE_STATES).where(
                    and_(
                        PROVIDER_MESSAGE_STATES.c.creator_id
                        == creator_id,
                        PROVIDER_MESSAGE_STATES.c.platform_message_id
                        == event.platform_message_id,
                    )
                )
            ).mappings().first()
            fan_id = (
                event.fan_id
                or (
                    str(existing_state["fan_id"])
                    if existing_state is not None
                    and existing_state["fan_id"]
                    else None
                )
                or self._resolve_fan_id(
                    connection,
                    creator_id=creator_id,
                    chat_id=event.chat_id,
                    supplied_fan_id=None,
                )
            )
            self._upsert_message_state(
                connection,
                creator_id=creator_id,
                platform_message_id=event.platform_message_id,
                chat_id=event.chat_id,
                fan_id=fan_id,
                direction=(
                    str(existing_state["direction"])
                    if existing_state is not None
                    else "unknown"
                ),
                source_class=(
                    str(existing_state["source_class"])
                    if existing_state is not None
                    and existing_state["source_class"]
                    else None
                ),
                provider_event_id=event.provider_event_id,
                provider_created_at=event.provider_created_at,
                deleted_at=event.provider_created_at,
                now=now,
            )
            connection.execute(
                update(FAN_MESSAGES)
                .where(
                    and_(
                        FAN_MESSAGES.c.creator_id == creator_id,
                        FAN_MESSAGES.c.message_id
                        == event.platform_message_id,
                    )
                )
                .values(
                    content="",
                    attachments=[],
                    deleted_at=event.provider_created_at,
                    provider_event_id=event.provider_event_id,
                )
            )

            target_inbound = connection.execute(
                select(INBOUND_MESSAGES).where(
                    and_(
                        INBOUND_MESSAGES.c.creator_id == creator_id,
                        INBOUND_MESSAGES.c.platform_message_id
                        == event.platform_message_id,
                    )
                )
            ).mappings().first()
            canceled = 0
            if target_inbound is not None:
                newer_exists = bool(
                    connection.execute(
                        select(INBOUND_MESSAGES.c.id)
                        .where(
                            and_(
                                INBOUND_MESSAGES.c.creator_id
                                == creator_id,
                                INBOUND_MESSAGES.c.fan_id
                                == target_inbound["fan_id"],
                                INBOUND_MESSAGES.c.provider_created_at
                                > target_inbound[
                                    "provider_created_at"
                                ],
                                INBOUND_MESSAGES.c.status.in_(
                                    ("pending", "processing")
                                ),
                            )
                        )
                        .limit(1)
                    ).first()
                )
                if not newer_exists:
                    canceled += connection.execute(
                        update(OUTBOX_MESSAGES)
                        .where(
                            and_(
                                OUTBOX_MESSAGES.c.inbound_message_id
                                == target_inbound["id"],
                                OUTBOX_MESSAGES.c.status == "pending",
                            )
                        )
                        .values(
                            status="cancelled_deleted",
                            permit_status="revoked",
                            last_error="triggering message was deleted",
                        )
                    ).rowcount
                    canceled += connection.execute(
                        update(INBOUND_MESSAGES)
                        .where(
                            and_(
                                INBOUND_MESSAGES.c.id
                                == target_inbound["id"],
                                INBOUND_MESSAGES.c.status.in_(
                                    ("pending", "processing")
                                ),
                            )
                        )
                        .values(
                            status="completed",
                            completed_at=now,
                            locked_at=None,
                            last_error="triggering message was deleted",
                        )
                    ).rowcount
        return WebhookIngestResult(
            True,
            None,
            canceled_count=int(canceled or 0),
        )

    def ingest_read(
        self,
        *,
        creator_id: str,
        event: OnlyFansApiFanslyReadReceipt,
    ) -> WebhookIngestResult:
        """Project read state only; never create conversation work."""
        now = datetime.now(timezone.utc)
        first_message_id = event.platform_message_ids[0]
        with self.engine.begin() as connection:
            if not self._insert_event(
                connection,
                creator_id=creator_id,
                event=event,
                platform_message_id=first_message_id,
                chat_id=event.chat_id,
                direction="unknown",
            ):
                return WebhookIngestResult(False, None)
            for platform_message_id in event.platform_message_ids:
                self._upsert_message_state(
                    connection,
                    creator_id=creator_id,
                    platform_message_id=platform_message_id,
                    chat_id=event.chat_id,
                    fan_id=event.fan_id,
                    direction="unknown",
                    source_class=None,
                    provider_event_id=event.provider_event_id,
                    provider_created_at=None,
                    read_at=event.provider_created_at,
                    now=now,
                )
            connection.execute(
                update(FAN_MESSAGES)
                .where(
                    and_(
                        FAN_MESSAGES.c.creator_id == creator_id,
                        FAN_MESSAGES.c.message_id.in_(
                            event.platform_message_ids
                        ),
                    )
                )
                .values(
                    read_at=event.provider_created_at,
                    provider_event_id=event.provider_event_id,
                )
            )
            if event.chat_id:
                connection.execute(
                    update(CONVERSATIONS)
                    .where(
                        and_(
                            CONVERSATIONS.c.creator_id == creator_id,
                            CONVERSATIONS.c.chat_id == event.chat_id,
                        )
                    )
                    .values(
                        last_read_at=case(
                            (
                                or_(
                                    CONVERSATIONS.c.last_read_at.is_(None),
                                    CONVERSATIONS.c.last_read_at
                                    <= event.provider_created_at,
                                ),
                                event.provider_created_at,
                            ),
                            else_=CONVERSATIONS.c.last_read_at,
                        ),
                        updated_at=now,
                    )
                )
        return WebhookIngestResult(True, None)

    def ingest_account(
        self,
        *,
        creator_id: str,
        event: OnlyFansApiFanslyAccountEvent,
    ) -> WebhookIngestResult:
        """Project connection health without ever restoring authority."""
        now = datetime.now(timezone.utc)
        authentication_failed = (
            event.event_name
            == "fansly.accounts.authentication_failed"
        )
        with self.engine.begin() as connection:
            if not self._insert_event(
                connection,
                creator_id=creator_id,
                event=event,
                platform_message_id=None,
                chat_id=None,
                direction="unknown",
            ):
                return WebhookIngestResult(False, None)

            state = self._insert(PROVIDER_CONNECTION_STATES).values(
                creator_id=creator_id,
                provider="onlyfansapi",
                connection_status=(
                    "authentication_failed"
                    if authentication_failed
                    else "connected"
                ),
                last_connected_at=(
                    None
                    if authentication_failed
                    else event.provider_created_at
                ),
                last_auth_failed_at=(
                    event.provider_created_at
                    if authentication_failed
                    else None
                ),
                updated_at=now,
            )
            state = state.on_conflict_do_update(
                index_elements=["creator_id", "provider"],
                set_={
                    "connection_status": (
                        "authentication_failed"
                        if authentication_failed
                        else "connected"
                    ),
                    "last_connected_at": (
                        PROVIDER_CONNECTION_STATES.c.last_connected_at
                        if authentication_failed
                        else event.provider_created_at
                    ),
                    "last_auth_failed_at": (
                        event.provider_created_at
                        if authentication_failed
                        else PROVIDER_CONNECTION_STATES.c.last_auth_failed_at
                    ),
                    "updated_at": now,
                },
            )
            connection.execute(state)

            if authentication_failed:
                circuit = self._insert(
                    PROVIDER_CIRCUIT_BREAKERS
                ).values(
                    creator_id=creator_id,
                    provider="onlyfansapi",
                    is_open=True,
                    reason_code="authentication_failed",
                    opened_at=event.provider_created_at,
                    operator_reset_at=None,
                    updated_at=now,
                )
                circuit = circuit.on_conflict_do_update(
                    index_elements=["creator_id", "provider"],
                    set_={
                        "is_open": True,
                        "reason_code": "authentication_failed",
                        "opened_at": event.provider_created_at,
                        "operator_reset_at": None,
                        "updated_at": now,
                    },
                )
                connection.execute(circuit)
                setting = self._insert(CREATOR_SETTINGS).values(
                    creator_id=creator_id,
                    key="bot_enabled",
                    value="false",
                    updated_at=now,
                )
                setting = setting.on_conflict_do_update(
                    index_elements=["creator_id", "key"],
                    set_={"value": "false", "updated_at": now},
                )
                connection.execute(setting)
                alert = self._insert(PROVIDER_ALERTS).values(
                    creator_id=creator_id,
                    provider="onlyfansapi",
                    event_key=event.event_key,
                    severity="critical",
                    code="authentication_failed",
                    message=(
                        "Fansly provider authentication failed; "
                        "sending and reconciliation are disabled."
                    ),
                    acknowledged_at=None,
                    created_at=now,
                )
                alert = alert.on_conflict_do_nothing(
                    index_elements=["creator_id", "event_key"]
                )
                connection.execute(alert)
        return WebhookIngestResult(True, None)

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

    def _insert_event(
        self,
        connection,
        *,
        creator_id: str,
        event,
        platform_message_id: str | None,
        chat_id: str | None,
        direction: str,
    ) -> bool:
        now = datetime.now(timezone.utc)
        statement = self._insert(PROVIDER_WEBHOOK_EVENTS).values(
            creator_id=creator_id,
            event_key=event.event_key,
            provider_event_id=event.provider_event_id,
            event_name=event.event_name,
            schema_version=event.schema_version,
            platform_message_id=platform_message_id,
            chat_id=chat_id,
            direction=direction,
            source_class="provider_webhook",
            status="accepted",
            error_category=None,
            provider_created_at=event.provider_created_at,
            received_at=now,
            processed_at=now,
        )
        statement = statement.on_conflict_do_nothing(
            index_elements=["creator_id", "event_key"]
        )
        return connection.execute(statement).rowcount == 1

    def _upsert_message_state(
        self,
        connection,
        *,
        creator_id: str,
        platform_message_id: str,
        chat_id: str | None,
        fan_id: str | None,
        direction: str,
        source_class: str | None,
        provider_event_id: str | None,
        provider_created_at: datetime | None,
        now: datetime,
        read_at: datetime | None = None,
        deleted_at: datetime | None = None,
    ):
        statement = self._insert(PROVIDER_MESSAGE_STATES).values(
            creator_id=creator_id,
            platform_message_id=platform_message_id,
            chat_id=chat_id,
            fan_id=fan_id,
            direction=direction,
            source_class=source_class,
            provider_event_id=provider_event_id,
            provider_created_at=provider_created_at,
            read_at=read_at,
            deleted_at=deleted_at,
            updated_at=now,
        )
        excluded = statement.excluded
        state = PROVIDER_MESSAGE_STATES
        statement = statement.on_conflict_do_update(
            index_elements=["creator_id", "platform_message_id"],
            set_={
                "chat_id": func.coalesce(
                    excluded.chat_id,
                    state.c.chat_id,
                ),
                "fan_id": func.coalesce(
                    excluded.fan_id,
                    state.c.fan_id,
                ),
                "direction": case(
                    (
                        excluded.direction != "unknown",
                        excluded.direction,
                    ),
                    else_=state.c.direction,
                ),
                "source_class": func.coalesce(
                    excluded.source_class,
                    state.c.source_class,
                ),
                "provider_event_id": func.coalesce(
                    excluded.provider_event_id,
                    state.c.provider_event_id,
                ),
                "provider_created_at": case(
                    (
                        or_(
                            state.c.provider_created_at.is_(None),
                            and_(
                                excluded.provider_created_at.is_not(None),
                                state.c.provider_created_at
                                <= excluded.provider_created_at,
                            ),
                        ),
                        excluded.provider_created_at,
                    ),
                    else_=state.c.provider_created_at,
                ),
                "read_at": case(
                    (
                        or_(
                            state.c.read_at.is_(None),
                            and_(
                                excluded.read_at.is_not(None),
                                state.c.read_at <= excluded.read_at,
                            ),
                        ),
                        excluded.read_at,
                    ),
                    else_=state.c.read_at,
                ),
                "deleted_at": case(
                    (
                        or_(
                            state.c.deleted_at.is_(None),
                            and_(
                                excluded.deleted_at.is_not(None),
                                state.c.deleted_at
                                <= excluded.deleted_at,
                            ),
                        ),
                        excluded.deleted_at,
                    ),
                    else_=state.c.deleted_at,
                ),
                "updated_at": now,
            },
        )
        connection.execute(statement)
        return connection.execute(
            select(PROVIDER_MESSAGE_STATES).where(
                and_(
                    PROVIDER_MESSAGE_STATES.c.creator_id == creator_id,
                    PROVIDER_MESSAGE_STATES.c.platform_message_id
                    == platform_message_id,
                )
            )
        ).mappings().one()

    def _ensure_fan(
        self,
        connection,
        *,
        creator_id: str,
        fan_id: str,
        now: datetime,
    ) -> None:
        statement = self._insert(FANS).values(
            creator_id=creator_id,
            fan_id=fan_id,
            display_name=None,
            username=None,
            avatar_url=None,
            created_at=now,
            updated_at=now,
        )
        statement = statement.on_conflict_do_update(
            index_elements=["creator_id", "fan_id"],
            set_={"updated_at": now},
        )
        connection.execute(statement)

    @staticmethod
    def _resolve_fan_id(
        connection,
        *,
        creator_id: str,
        chat_id: str | None,
        supplied_fan_id: str | None,
    ) -> str | None:
        if supplied_fan_id:
            return str(supplied_fan_id)
        if not chat_id:
            return None
        value = connection.execute(
            select(CONVERSATIONS.c.fan_id).where(
                and_(
                    CONVERSATIONS.c.creator_id == creator_id,
                    CONVERSATIONS.c.chat_id == chat_id,
                )
            )
        ).scalar_one_or_none()
        return str(value) if value else None

    def _upsert_conversation_activity(
        self,
        connection,
        *,
        creator_id: str,
        fan_id: str,
        chat_id: str,
        platform_message_id: str,
        speaker: str,
        provider_created_at: datetime,
        now: datetime,
    ) -> None:
        values = {
            "creator_id": creator_id,
            "chat_id": chat_id,
            "fan_id": fan_id,
            "provider_cursor": None,
            "last_platform_message_id": platform_message_id,
            "last_activity_at": provider_created_at,
            "last_speaker": speaker,
            "last_fan_message_at": (
                provider_created_at if speaker == "fan" else None
            ),
            "last_creator_message_at": (
                provider_created_at if speaker == "creator" else None
            ),
            "last_read_at": None,
            "created_at": now,
            "updated_at": now,
        }
        statement = self._insert(CONVERSATIONS).values(**values)
        chat_changed = (
            CONVERSATIONS.c.chat_id != statement.excluded.chat_id
        )
        newer = or_(
            CONVERSATIONS.c.last_activity_at.is_(None),
            CONVERSATIONS.c.last_activity_at <= provider_created_at,
        )
        speaker_column = (
            CONVERSATIONS.c.last_fan_message_at
            if speaker == "fan"
            else CONVERSATIONS.c.last_creator_message_at
        )
        statement = statement.on_conflict_do_update(
            index_elements=["creator_id", "fan_id"],
            set_={
                "chat_id": statement.excluded.chat_id,
                "provider_cursor": case(
                    (chat_changed, None),
                    else_=CONVERSATIONS.c.provider_cursor,
                ),
                "last_platform_message_id": case(
                    (newer, platform_message_id),
                    else_=CONVERSATIONS.c.last_platform_message_id,
                ),
                "last_activity_at": case(
                    (newer, provider_created_at),
                    else_=CONVERSATIONS.c.last_activity_at,
                ),
                "last_speaker": case(
                    (newer, speaker),
                    else_=CONVERSATIONS.c.last_speaker,
                ),
                (
                    "last_fan_message_at"
                    if speaker == "fan"
                    else "last_creator_message_at"
                ): case(
                    (
                        or_(
                            speaker_column.is_(None),
                            speaker_column <= provider_created_at,
                        ),
                        provider_created_at,
                    ),
                    else_=speaker_column,
                ),
                "updated_at": now,
            },
        )
        connection.execute(statement)

    @staticmethod
    def _sent_source_class(
        event: OnlyFansApiFanslySentMessage,
        matched_outbox,
    ) -> str:
        if matched_outbox is not None:
            return "ai"
        hint = str(event.source_hint or "").strip().casefold()
        if event.automation_id or "automation" in hint:
            return "native_automation"
        if (
            event.integration_id
            or "integration" in hint
            or "api" in hint
        ):
            return "external_api"
        return "manual"

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _insert(self, table):
        if self.engine.dialect.name == "postgresql":
            return pg_insert(table)
        return sqlite_insert(table)
