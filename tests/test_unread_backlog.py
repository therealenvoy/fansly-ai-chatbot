"""Focused tests for the bounded unread-backlog operator control."""

from contextlib import nullcontext
from unittest.mock import MagicMock

from src.bot import UnreadBacklogBatchResult
from src.persistence.database import create_database_engine
from src.persistence.schema import metadata
from src.persistence.state import ConversationStateRepository
from src.unread_backlog import UnreadBacklogController


def _controller():
    engine = create_database_engine(
        "sqlite:///:memory:",
        environment={"APP_ENV": "test"},
    )
    metadata.create_all(engine)
    repository = ConversationStateRepository(engine)
    bot = MagicMock()
    bot.creator_id = "creator-test"
    bot.enabled = True
    bot.enable_unread_replies = True
    bot.client.list_unread_chats_page = MagicMock()
    wakeup = MagicMock()
    controller = UnreadBacklogController(
        bot=bot,
        state_repo=repository,
        inbound_wakeup=wakeup,
        guard_factory=nullcontext,
    )
    return controller, bot, wakeup


def test_run_persists_aggregate_progress_and_wakes_reply_worker():
    controller, bot, wakeup = _controller()
    bot.import_unread_backlog_batch.return_value = (
        UnreadBacklogBatchResult(
            discovered_chats=8,
            processed_chats=5,
            queued_inbound=4,
            skipped_chats=0,
            next_cursor="provider-cursor-sanitized",
            exhausted=False,
        )
    )

    controller._run(5)

    snapshot = controller.snapshot()
    assert snapshot["phase"] == "awaiting_review"
    assert snapshot["processed_chats"] == 5
    assert snapshot["queued_inbound"] == 4
    assert snapshot["last_batch_queued"] == 4
    assert "provider_cursor" not in snapshot
    wakeup.set.assert_called_once_with()


def test_empty_page_completes_without_waking_or_sending():
    controller, bot, wakeup = _controller()
    bot.import_unread_backlog_batch.return_value = (
        UnreadBacklogBatchResult(
            discovered_chats=0,
            processed_chats=0,
            queued_inbound=0,
            skipped_chats=0,
            next_cursor=None,
            exhausted=True,
        )
    )

    controller._run(5)

    snapshot = controller.snapshot()
    assert snapshot["phase"] == "complete"
    assert snapshot["queued_inbound"] == 0
    wakeup.set.assert_not_called()


def test_explicit_creator_id_avoids_mock_runtime_identifier():
    engine = create_database_engine(
        "sqlite:///:memory:",
        environment={"APP_ENV": "test"},
    )
    metadata.create_all(engine)
    repository = ConversationStateRepository(engine)
    bot = MagicMock()
    bot.creator_id = MagicMock()
    bot.enabled = True
    bot.enable_unread_replies = True
    bot.client.list_unread_chats_page = MagicMock()

    controller = UnreadBacklogController(
        bot=bot,
        state_repo=repository,
        creator_id="creator-config",
    )

    assert controller.creator_id == "creator-config"
    assert controller.snapshot()["phase"] == "not_started"
