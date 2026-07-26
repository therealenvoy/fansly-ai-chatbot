"""Send one explicitly approved controlled-launch reply exactly once.

The command validates provider state and durable inbox/outbox state before
making a send. Without ``--execute`` it is read-only.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from sqlalchemy import and_, select

from src.client_factory import get_fansly_client
from src.messaging.models import OutboundMessage
from src.messaging.policy import MessageContentPolicy
from src.persistence.database import create_database_engine
from src.persistence.pipeline import (
    INBOUND_PENDING,
    INBOUND_PROCESSING,
    OUTBOX_SENT,
    MessageProcessingRepository,
)
from src.persistence.schema import (
    FAN_MESSAGES,
    INBOUND_MESSAGES,
    OUTBOX_MESSAGES,
)
from src.persistence.state import ConversationStateRepository
from src.persona.loader import PersonaLoader
from src.persona.validator import PersonaValidator


def _enabled(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _provider_datetime(timestamp: float) -> datetime:
    numeric = float(timestamp or 0)
    if numeric > 10_000_000_000:
        numeric /= 1000
    return datetime.fromtimestamp(numeric, timezone.utc)


def _find_chat(client, fan_id: str):
    offset = 0
    for _ in range(10):
        chats, next_offset = client.list_chats_page(
            limit=100,
            offset=offset,
            order="newest",
        )
        for chat in chats:
            if chat.partner_account_id == fan_id:
                return chat
        if next_offset is None:
            break
        offset = next_offset
    raise RuntimeError(f"pilot fan {fan_id} was not found in provider chats")


def _find_message(client, chat_id: str, message_id: str):
    cursor = None
    for _ in range(10):
        messages, next_cursor = client.list_messages(
            chat_id,
            limit=100,
            cursor=cursor,
        )
        for message in messages:
            if message.message_id == message_id:
                return message
        if not next_cursor:
            break
        cursor = next_cursor
    raise RuntimeError(
        f"approved inbound message {message_id} was not found"
    )


def _existing_delivery(engine, creator_id: str, message_id: str):
    with engine.connect() as conn:
        inbound = conn.execute(
            select(INBOUND_MESSAGES).where(
                and_(
                    INBOUND_MESSAGES.c.creator_id == creator_id,
                    INBOUND_MESSAGES.c.platform_message_id == message_id,
                )
            )
        ).mappings().first()
        if inbound is None:
            return None, None
        outbox = conn.execute(
            select(OUTBOX_MESSAGES).where(
                OUTBOX_MESSAGES.c.inbound_message_id == inbound["id"]
            )
        ).mappings().first()
    return inbound, outbox


def _assert_no_competing_work(engine, creator_id: str, fan_id: str) -> None:
    with engine.connect() as conn:
        row = conn.execute(
            select(INBOUND_MESSAGES.c.id).where(
                and_(
                    INBOUND_MESSAGES.c.creator_id == creator_id,
                    INBOUND_MESSAGES.c.fan_id == fan_id,
                    INBOUND_MESSAGES.c.status.in_(
                        (INBOUND_PENDING, INBOUND_PROCESSING)
                    ),
                )
            )
        ).first()
    if row is not None:
        raise RuntimeError(
            "another pending/processing inbound exists for the pilot fan"
        )


def _save_history_once(
    engine,
    *,
    creator_id: str,
    fan_id: str,
    sender: str,
    content: str,
    message_id: str,
    created_at: datetime,
) -> None:
    with engine.begin() as conn:
        exists = conn.execute(
            select(FAN_MESSAGES.c.id).where(
                and_(
                    FAN_MESSAGES.c.creator_id == creator_id,
                    FAN_MESSAGES.c.fan_id == fan_id,
                    FAN_MESSAGES.c.message_id == message_id,
                )
            )
        ).first()
        if exists is None:
            conn.execute(
                FAN_MESSAGES.insert().values(
                    fan_id=fan_id,
                    creator_id=creator_id,
                    sender=sender,
                    content=content,
                    message_id=message_id,
                    created_at=created_at,
                )
            )


def _validate_environment(environment: dict[str, str], fan_id: str) -> None:
    if environment.get("FANSLY_PROVIDER", "").strip() != "fanslyapi":
        raise RuntimeError("FANSLY_PROVIDER must be fanslyapi")
    if not _enabled(environment.get("CONTROLLED_LAUNCH"), default=True):
        raise RuntimeError("CONTROLLED_LAUNCH must remain true")
    if _enabled(environment.get("BOT_ENABLED_DEFAULT"), default=False):
        raise RuntimeError("BOT_ENABLED_DEFAULT must remain false")
    allowlist = {
        value.strip()
        for value in environment.get("FAN_ALLOWLIST", "").split(",")
        if value.strip()
    }
    if allowlist != {fan_id}:
        raise RuntimeError(
            "FAN_ALLOWLIST must contain only the approved pilot fan"
        )


def run(args: argparse.Namespace, environment: dict[str, str]) -> dict:
    _validate_environment(environment, args.fan_id)
    creator_id = environment.get("CREATOR_ID", "sunny_charm")
    outbound_policy = MessageContentPolicy().validate_outbound(args.message)
    if not outbound_policy.approved:
        raise RuntimeError(outbound_policy.reason)

    persona_dir = Path(args.persona_dir)
    persona = PersonaLoader(config_dir=str(persona_dir)).load(creator_id)
    voice = PersonaValidator(persona).validate(outbound_policy.content)
    if not voice.passed:
        raise RuntimeError(
            "approved reply violates persona: " + ", ".join(voice.violations)
        )

    client = get_fansly_client(environment)
    chat = _find_chat(client, args.fan_id)
    if chat.unread_count <= 0:
        raise RuntimeError("pilot chat no longer has an unread message")
    if chat.last_unread_message_id != args.inbound_message_id:
        raise RuntimeError(
            "pilot chat changed; last unread message no longer matches approval"
        )
    inbound_message = _find_message(
        client,
        chat.chat_id,
        args.inbound_message_id,
    )
    if not inbound_message.is_from_fan:
        raise RuntimeError("approved inbound message is not fan-authored")
    inbound_policy = MessageContentPolicy().validate_inbound(
        inbound_message.content
    )
    if not inbound_policy.approved:
        raise RuntimeError(inbound_policy.reason)

    engine = create_database_engine(
        environment.get("DATABASE_URL", ""),
        environment=environment,
    )
    processing = MessageProcessingRepository(engine)
    state = ConversationStateRepository(engine)
    existing_inbound, existing_outbox = _existing_delivery(
        engine,
        creator_id,
        args.inbound_message_id,
    )
    if existing_inbound is not None:
        if (
            existing_outbox is not None
            and existing_outbox["status"] == OUTBOX_SENT
            and existing_outbox["content"] == outbound_policy.content
            and existing_outbox["provider_message_id"]
        ):
            return {
                "status": "already_sent",
                "inbound_message_id": args.inbound_message_id,
                "outbound_message_id": existing_outbox[
                    "provider_message_id"
                ],
            }
        raise RuntimeError(
            "durable state already exists for this inbound; refusing to send"
        )
    _assert_no_competing_work(engine, creator_id, args.fan_id)

    if not args.execute:
        return {
            "status": "dry_run_pass",
            "fan_id": args.fan_id,
            "inbound_message_id": args.inbound_message_id,
            "approved_message": outbound_policy.content,
            "bot_enabled_default": False,
        }

    state.ensure_conversation(
        creator_id,
        args.fan_id,
        chat.chat_id,
        display_name=chat.partner_display_name,
    )
    state.load_session(creator_id, args.fan_id)
    inbound, created = processing.insert_inbound(
        creator_id=creator_id,
        platform_message_id=args.inbound_message_id,
        fan_id=args.fan_id,
        chat_id=chat.chat_id,
        content=inbound_policy.content,
        provider_created_at=_provider_datetime(
            inbound_message.created_at
        ),
    )
    if not created:
        raise RuntimeError("inbound was inserted concurrently; refusing to send")
    claimed = processing.claim_next_inbound(
        creator_id,
        allowed_fan_ids={args.fan_id},
    )
    if claimed is None or claimed.id != inbound.id:
        raise RuntimeError("failed to claim the exact approved inbound")
    outbox, created = processing.enqueue_outbox(
        inbound=claimed,
        message=OutboundMessage.text(outbound_policy.content),
    )
    if not created:
        raise RuntimeError("outbox already exists; refusing to send")
    sending = processing.claim_outbox(outbox.id)
    if sending is None:
        raise RuntimeError("failed to claim the approved outbox")
    try:
        sent = client.send_message(chat.chat_id, outbound_policy.content)
        if not sent.success or not sent.message_id:
            raise RuntimeError("provider did not confirm an outbound message ID")
    except Exception as exc:
        processing.mark_delivery_unknown(sending.id, str(exc))
        raise

    sent_row, completed = processing.complete_delivery(
        sending.id,
        sent.message_id,
    )
    state.update_conversation_checkpoint(
        creator_id,
        chat.chat_id,
        last_platform_message_id=(
            chat.last_message_id or args.inbound_message_id
        ),
        last_activity_at=_provider_datetime(inbound_message.created_at),
    )
    _save_history_once(
        engine,
        creator_id=creator_id,
        fan_id=args.fan_id,
        sender="fan",
        content=inbound_policy.content,
        message_id=args.inbound_message_id,
        created_at=_provider_datetime(inbound_message.created_at),
    )
    _save_history_once(
        engine,
        creator_id=creator_id,
        fan_id=args.fan_id,
        sender="creator",
        content=outbound_policy.content,
        message_id=sent.message_id,
        created_at=_provider_datetime(sent.created_at),
    )
    return {
        "status": "sent",
        "fan_id": args.fan_id,
        "inbound_message_id": completed.platform_message_id,
        "outbound_message_id": sent_row.provider_message_id,
        "inbound_status": completed.status,
        "outbox_status": sent_row.status,
        "bot_enabled_default": False,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--fan-id", required=True)
    result.add_argument("--inbound-message-id", required=True)
    result.add_argument("--message", required=True)
    result.add_argument(
        "--persona-dir",
        default="config/creators",
    )
    result.add_argument(
        "--execute",
        action="store_true",
        help="Perform the approved send; without this flag the command is read-only.",
    )
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        result = run(args, dict(os.environ))
    except Exception as exc:
        print(
            json.dumps(
                {"status": "blocked", "error": str(exc)},
                ensure_ascii=True,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
