"""End-to-end tests for the provider-to-CRM history synchronizer."""

from unittest.mock import MagicMock

from sqlalchemy import func, select

from src.crm.sync import CrmSyncService
from src.fansly_client import ChatInfo, FanslyApiClient, MessageInfo
from src.memory.store import MessageStore
from src.persistence.crm import CrmSyncRepository
from src.persistence.database import create_database_engine
from src.persistence.schema import INBOUND_MESSAGES, metadata
from src.persistence.state import ConversationStateRepository


def _message(
    message_id: str,
    content: str,
    created_at: float,
    *,
    fan: bool,
) -> MessageInfo:
    return MessageInfo(
        message_id=message_id,
        content=content,
        sender_id="fan-1" if fan else "creator-1",
        created_at=created_at,
        is_from_fan=fan,
        has_attachments=not bool(content),
        attachments=(
            [{"type": "video", "id": f"media-{message_id}"}]
            if not content
            else []
        ),
    )


def _service(*, message_page_budget: int = 10):
    engine = create_database_engine(
        "sqlite:///:memory:",
        environment={"APP_ENV": "test"},
    )
    metadata.create_all(engine)
    client = MagicMock(spec=FanslyApiClient)
    client.account_id = "account-1"
    store = MessageStore(engine=engine)
    state = ConversationStateRepository(engine)
    state.ensure_creator("creator-1")
    service = CrmSyncService(
        client=client,
        creator_id="creator-1",
        state_repo=state,
        sync_repo=CrmSyncRepository(engine),
        message_store=store,
        message_page_budget=message_page_budget,
        discovery_page_budget=1,
    )
    return service, client, store, engine


def test_sync_imports_every_discovered_chat_while_automation_is_disabled():
    service, client, store, engine = _service()
    chats = [
        ChatInfo(
            chat_id="chat-1",
            partner_account_id="fan-1",
            partner_username="fan_one",
            partner_display_name="Fan One",
            unread_count=0,
            last_message_id="message-2",
        ),
        ChatInfo(
            chat_id="chat-2",
            partner_account_id="fan-2",
            partner_username="fan_two",
            partner_display_name="Fan Two",
            unread_count=0,
            last_message_id="message-3",
        ),
    ]
    client.list_chats_page.return_value = (chats, None)

    def list_messages(chat_id, *, limit, cursor):
        assert limit == 100
        assert cursor is None
        if chat_id == "chat-1":
            return (
                [
                    _message("message-2", "", 20, fan=False),
                    _message("message-1", "hello", 10, fan=True),
                ],
                None,
            )
        return ([_message("message-3", "hey", 30, fan=True)], None)

    client.list_messages.side_effect = list_messages

    result = service.sync_cycle()

    assert result.discovered_chats == 2
    assert result.inserted_messages == 3
    assert [row["content"] for row in store.get_history("fan-1", "creator-1")] == [
        "hello",
        "",
    ]
    assert store.get_history("fan-1", "creator-1")[1]["sender"] == "creator"
    assert store.get_history("fan-1", "creator-1")[1]["attachments"] == [
        {"type": "video", "id": "media-message-2"}
    ]
    assert store.count_messages("fan-2", "creator-1") == 1
    with engine.connect() as connection:
        queued_for_reply = connection.execute(
            select(func.count()).select_from(INBOUND_MESSAGES)
        ).scalar_one()
    assert queued_for_reply == 0

    second = service.sync_cycle()
    assert second.inserted_messages == 0
    assert client.list_messages.call_count == 2
    assert store.count_messages("fan-1", "creator-1") == 2


def test_sync_resumes_deep_history_and_then_catches_new_messages():
    service, client, store, _ = _service(message_page_budget=1)
    chat = ChatInfo(
        chat_id="chat-1",
        partner_account_id="fan-1",
        partner_username="fan_one",
        partner_display_name="Fan One",
        last_message_id="message-3",
    )
    client.list_chats_page.return_value = ([chat], None)
    client.list_messages.side_effect = [
        (
            [
                _message("message-3", "newest", 30, fan=True),
                _message("message-2", "middle", 20, fan=False),
            ],
            "older-page",
        ),
        ([_message("message-1", "oldest", 10, fan=True)], None),
    ]

    first = service.sync_cycle()
    second = service.sync_cycle()

    assert first.inserted_messages == 2
    assert first.remaining_chats == 1
    assert second.inserted_messages == 1
    assert second.remaining_chats == 0
    assert [row["content"] for row in store.get_history("fan-1", "creator-1")] == [
        "oldest",
        "middle",
        "newest",
    ]
    assert client.list_messages.call_args_list[1].kwargs["cursor"] == "older-page"

    chat.last_message_id = "message-4"
    client.list_messages.side_effect = None
    client.list_messages.return_value = (
        [
            _message("message-4", "brand new", 40, fan=True),
            _message("message-3", "newest", 30, fan=True),
        ],
        None,
    )

    third = service.sync_cycle()

    assert third.inserted_messages == 1
    assert [row["content"] for row in store.get_history("fan-1", "creator-1")] == [
        "oldest",
        "middle",
        "newest",
        "brand new",
    ]
