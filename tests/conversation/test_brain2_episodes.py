from datetime import datetime, timedelta, timezone

from src.conversation.brain2_episodes import (
    ConversationEpisodeService,
    EvidenceBoundEpisodeSummarizer,
)
from src.conversation.brain2_repository import ConversationEpisodeRepository
from src.persistence.database import create_database_engine
from src.persistence.schema import metadata
from src.persistence.state import ConversationStateRepository


class _HistoryPage:
    def __init__(self, messages, total):
        self.messages = messages
        self.total = total


class _MessageStore:
    def __init__(self, messages):
        self.messages = messages

    def get_history_page(self, fan_id, creator_id, *, limit, offset):
        newest_first = list(reversed(self.messages))
        page = newest_first[offset : offset + limit]
        return _HistoryPage(list(reversed(page)), len(self.messages))


def _engine():
    engine = create_database_engine(
        "sqlite:///:memory:",
        environment={"APP_ENV": "test"},
    )
    metadata.create_all(engine)
    ConversationStateRepository(engine).ensure_conversation(
        "creator-a",
        "fan-a",
        "chat-a",
    )
    return engine


def test_episode_service_summarizes_only_older_history_idempotently():
    now = datetime.now(timezone.utc)
    messages = [
        {
            "id": index,
            "message_id": f"m-{index}",
            "sender": "fan" if index % 2 else "creator",
            "content": (
                "I work a night shift and feel tired"
                if index == 3
                else f"conversation message {index}"
            ),
            "created_at": (now + timedelta(minutes=index)).isoformat(),
        }
        for index in range(1, 13)
    ]
    engine = _engine()
    repository = ConversationEpisodeRepository(engine)
    service = ConversationEpisodeService(
        creator_id="creator-a",
        message_store=_MessageStore(messages),
        repository=repository,
        summarizer=EvidenceBoundEpisodeSummarizer(),
        recent_keep=4,
        episode_size=6,
        max_workers=1,
    )

    first = service.submit("fan-a")
    service.wait_for_idle()
    second = service.submit("fan-a")
    service.wait_for_idle()
    service.shutdown()

    assert first is True
    assert second is True
    episodes = repository.recent(
        creator_id="creator-a",
        fan_id="fan-a",
        limit=10,
    )
    assert len(episodes) == 1
    assert episodes[0]["source_start_message_id"] == "m-3"
    assert episodes[0]["source_end_message_id"] == "m-8"
    assert episodes[0]["fan_disclosures"] == [
        "I work a night shift and feel tired"
    ]


def test_episode_summary_never_invents_disclosure_text():
    now = datetime.now(timezone.utc)
    messages = [
        {
            "id": 1,
            "message_id": "m-1",
            "sender": "fan",
            "content": "I like old horror movies",
            "created_at": now.isoformat(),
        },
        {
            "id": 2,
            "message_id": "m-2",
            "sender": "creator",
            "content": "which one is your favorite?",
            "created_at": (now + timedelta(minutes=1)).isoformat(),
        },
    ]

    summary = EvidenceBoundEpisodeSummarizer().summarize(messages)

    assert summary["fan_disclosures"] == ["I like old horror movies"]
    assert all(
        item in {message["content"] for message in messages}
        for item in (
            summary["fan_disclosures"]
            + summary["creator_statements"]
            + summary["boundaries"]
            + summary["unresolved_threads"]
        )
    )
