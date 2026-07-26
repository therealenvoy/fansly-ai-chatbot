"""Read-only provider history synchronization for the creator CRM.

This service is deliberately separate from automated reply processing:
it imports every discovered conversation, both sides of each chat, and
historical pages even while the bot is paused.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from src.fansly_client import ChatInfo, FanslyApiClient, MessageInfo
from src.memory.store import MessageStore
from src.persistence.crm import CrmChatSyncState, CrmSyncRepository
from src.persistence.state import ConversationStateRepository


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CrmSyncCycleResult:
    discovered_chats: int
    message_pages: int
    inserted_messages: int
    remaining_chats: int
    discovery_complete: bool

    @property
    def had_activity(self) -> bool:
        return bool(self.inserted_messages or self.discovered_chats)


class CrmSyncService:
    """Incrementally mirror provider conversations into the durable CRM."""

    DISCOVERY_SCOPE = "crm:chat-discovery"
    DISCOVERY_DONE = "done"

    def __init__(
        self,
        *,
        client: FanslyApiClient,
        creator_id: str,
        state_repo: ConversationStateRepository,
        sync_repo: CrmSyncRepository,
        message_store: MessageStore,
        message_page_budget: int = 25,
        discovery_page_budget: int = 2,
    ):
        self.client = client
        self.creator_id = creator_id
        self.state_repo = state_repo
        self.sync_repo = sync_repo
        self.message_store = message_store
        self.message_page_budget = min(
            max(int(message_page_budget), 1),
            100,
        )
        self.discovery_page_budget = min(
            max(int(discovery_page_budget), 1),
            10,
        )

    def sync_cycle(self) -> CrmSyncCycleResult:
        discovered, discovery_complete = self._discover_chats()
        inserted = 0
        pages = 0
        for state in self.sync_repo.pending(
            self.creator_id,
            limit=self.message_page_budget,
        ):
            try:
                page_inserted, requested = self._sync_message_page(state)
                inserted += page_inserted
                pages += int(requested)
            except Exception as error:
                self.sync_repo.mark_error(
                    creator_id=self.creator_id,
                    chat_id=state.chat_id,
                    error=error,
                )
                logger.exception(
                    "CRM message sync failed for chat %s",
                    state.chat_id,
                )
        remaining = self.sync_repo.remaining(self.creator_id)
        if discovered or inserted or pages:
            logger.info(
                "CRM sync: discovered=%s pages=%s inserted=%s remaining=%s",
                discovered,
                pages,
                inserted,
                remaining,
            )
        return CrmSyncCycleResult(
            discovered_chats=discovered,
            message_pages=pages,
            inserted_messages=inserted,
            remaining_chats=remaining,
            discovery_complete=discovery_complete,
        )

    def _discover_chats(self) -> tuple[int, bool]:
        discovered_ids: set[str] = set()
        first_page, next_cursor = self.client.list_chats_page(
            limit=100,
            offset=0,
            order="newest",
        )
        self._record_discovered(first_page, discovered_ids)

        stored = self.state_repo.get_poll_cursor(
            self.creator_id,
            self.DISCOVERY_SCOPE,
        )
        if stored is None:
            stored = (
                self._encode_cursor(next_cursor)
                if next_cursor is not None
                else self.DISCOVERY_DONE
            )

        extra_pages = self.discovery_page_budget - 1
        while stored != self.DISCOVERY_DONE and extra_pages > 0:
            cursor = self._decode_cursor(stored)
            page, next_cursor = self.client.list_chats_page(
                limit=100,
                offset=cursor,
                order="newest",
            )
            self._record_discovered(page, discovered_ids)
            stored = (
                self._encode_cursor(next_cursor)
                if next_cursor is not None
                else self.DISCOVERY_DONE
            )
            extra_pages -= 1

        self.state_repo.set_poll_cursor(
            self.creator_id,
            self.DISCOVERY_SCOPE,
            stored,
        )
        return len(discovered_ids), stored == self.DISCOVERY_DONE

    def _record_discovered(
        self,
        chats: list[ChatInfo],
        discovered_ids: set[str],
    ) -> None:
        conversation_rows = []
        sync_rows = []
        for chat in chats:
            discovered_ids.add(chat.chat_id)
            conversation_rows.append(
                {
                    "fan_id": chat.partner_account_id,
                    "chat_id": chat.chat_id,
                    "display_name": chat.partner_display_name,
                    "username": chat.partner_username,
                    "avatar_url": chat.avatar_url,
                }
            )
            sync_rows.append(
                {
                    "chat_id": chat.chat_id,
                    "fan_id": chat.partner_account_id,
                    "provider_head_message_id": chat.last_message_id,
                }
            )
        self.state_repo.ensure_conversations(
            self.creator_id,
            conversation_rows,
        )
        self.sync_repo.discover_chats(
            creator_id=self.creator_id,
            chats=sync_rows,
        )

    def _sync_message_page(
        self,
        state: CrmChatSyncState,
    ) -> tuple[int, bool]:
        if state.has_new_head or state.last_synced_at is None:
            return self._sync_incremental_page(state), True
        if state.history_complete:
            return 0, False
        if state.backfill_cursor is None:
            self.sync_repo.advance_backfill(
                creator_id=self.creator_id,
                chat_id=state.chat_id,
                cursor=None,
            )
            return 0, False
        return self._sync_backfill_page(state), True

    def _sync_incremental_page(self, state: CrmChatSyncState) -> int:
        cursor = state.incremental_cursor
        messages, next_cursor = self.client.list_messages(
            state.chat_id,
            limit=100,
            cursor=cursor,
        )
        inserted = self._save_messages(state, messages)
        target = state.stored_head_message_id

        if target is None:
            provider_head = (
                state.provider_head_message_id
                or self._newest_message_id(messages)
            )
            self.sync_repo.complete_initial_page(
                creator_id=self.creator_id,
                chat_id=state.chat_id,
                provider_head_message_id=provider_head,
                backfill_cursor=next_cursor,
            )
            return inserted

        found_target = any(
            message.message_id == target
            for message in messages
        )
        if found_target or next_cursor is None:
            self.sync_repo.complete_incremental(
                creator_id=self.creator_id,
                chat_id=state.chat_id,
                provider_head_message_id=state.provider_head_message_id,
            )
            return inserted
        if next_cursor == cursor:
            raise RuntimeError(
                f"Repeated incremental message cursor for {state.chat_id}"
            )
        self.sync_repo.continue_incremental(
            creator_id=self.creator_id,
            chat_id=state.chat_id,
            cursor=next_cursor,
        )
        return inserted

    def _sync_backfill_page(self, state: CrmChatSyncState) -> int:
        messages, next_cursor = self.client.list_messages(
            state.chat_id,
            limit=100,
            cursor=state.backfill_cursor,
        )
        if next_cursor == state.backfill_cursor:
            raise RuntimeError(
                f"Repeated backfill message cursor for {state.chat_id}"
            )
        inserted = self._save_messages(state, messages)
        self.sync_repo.advance_backfill(
            creator_id=self.creator_id,
            chat_id=state.chat_id,
            cursor=next_cursor,
        )
        return inserted

    def _save_messages(
        self,
        state: CrmChatSyncState,
        messages: list[MessageInfo],
    ) -> int:
        newest_at: datetime | None = None
        rows: list[dict] = []
        for message in sorted(
            messages,
            key=lambda row: (row.created_at, row.message_id),
        ):
            created_at = self._provider_datetime(message.created_at)
            rows.append(
                {
                    "fan_id": state.fan_id,
                    "creator_id": self.creator_id,
                    "sender": (
                        "fan" if message.is_from_fan else "creator"
                    ),
                    "content": message.content,
                    "message_id": message.message_id,
                    "chat_id": state.chat_id,
                    "attachments": message.attachments,
                    "created_at": created_at,
                }
            )
            if newest_at is None or created_at > newest_at:
                newest_at = created_at
        inserted = self.message_store.save_messages(rows)
        if newest_at is not None:
            self.state_repo.record_crm_activity(
                self.creator_id,
                state.chat_id,
                last_activity_at=newest_at,
            )
        return inserted

    @staticmethod
    def _newest_message_id(messages: list[MessageInfo]) -> str | None:
        newest = max(
            messages,
            key=lambda row: (row.created_at, row.message_id),
            default=None,
        )
        return newest.message_id if newest is not None else None

    @staticmethod
    def _provider_datetime(timestamp: float) -> datetime:
        numeric = float(timestamp or 0)
        if numeric > 10_000_000_000:
            numeric /= 1000
        return datetime.fromtimestamp(numeric, timezone.utc)

    @staticmethod
    def _encode_cursor(cursor: int | str) -> str:
        return json.dumps(
            {
                "type": "int" if isinstance(cursor, int) else "str",
                "value": cursor,
            },
            separators=(",", ":"),
        )

    @staticmethod
    def _decode_cursor(value: str) -> int | str:
        parsed = json.loads(value)
        if parsed.get("type") == "int":
            return int(parsed["value"])
        return str(parsed["value"])
