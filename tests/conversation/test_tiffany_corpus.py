from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import func, insert, select

from src.conversation.brain2_schema import FAN_MEMORIES_V2
from src.conversation.intelligence_v3.corpus import CorpusIngestor, load_compiled_corpus
from src.conversation.intelligence_v3.repository import KnowledgeRepository
from src.conversation.intelligence_v3.retrieval import MemoryRetrieverV3
from src.conversation.intelligence_v3.schema import (
    CONVERSATION_CORPUS_RELEASES,
    CONVERSATION_INTELLIGENCE_RUNS,
)
from src.conversation.intelligence_v3.service import ConversationIntelligenceV3Service
from src.conversation.intelligence_v3.settings import V3RuntimeSettings
from src.persistence.database import create_database_engine
from src.persistence.pipeline import MessageProcessingRepository
from src.persistence.schema import CREATORS, OUTBOX_MESSAGES, metadata, utcnow
from src.persistence.state import ConversationStateRepository


ARTIFACT = Path(__file__).resolve().parents[2] / "artifacts" / "tiffany-training-v1.json"


def _engine():
    engine = create_database_engine("sqlite:///:memory:", environment={"APP_ENV": "test"})
    metadata.create_all(engine)
    now = utcnow()
    with engine.begin() as connection:
        connection.execute(insert(CREATORS).values(id="creator-tiffany", created_at=now, updated_at=now))
    return engine


def _memory(connection, *, memory_type: str, value: str, confidence: float = 0.95):
    now = datetime(2026, 8, 2, tzinfo=timezone.utc)
    connection.execute(
        insert(FAN_MEMORIES_V2).values(
            creator_id="creator-tiffany",
            fan_id="fan-a",
            memory_type=memory_type,
            memory_key=memory_type,
            normalized_value=value.lower(),
            display_value=value,
            confidence=confidence,
            importance=1.0,
            source_message_id=f"source-{memory_type}",
            source_timestamp=now,
            first_seen_at=now,
            last_confirmed_at=now,
            expires_at=None,
            status="active",
            sensitivity_class="standard",
            contradiction_status="clear",
            created_at=now,
            updated_at=now,
        )
    )


class _Dumpable(SimpleNamespace):
    def model_dump(self, **kwargs):
        excluded = set(kwargs.get("exclude") or set())
        return {key: value for key, value in vars(self).items() if key not in excluded}


class _Diversity:
    def evaluate(self, message, **kwargs):
        return SimpleNamespace(fingerprint=f"fingerprint-{len(message)}")


class _Planner:
    model = "deepseek-v4-flash"
    diversity = _Diversity()

    def __init__(self):
        self.compiled = None

    def generate(self, compiled, **kwargs):
        self.compiled = compiled
        candidate = SimpleNamespace(message="that sounds like a long shift", act="acknowledge")
        plan = SimpleNamespace(
            understanding=SimpleNamespace(
                emotion="tired",
                intent="share_work",
                underlying_need="recognition",
                evidence=[SimpleNamespace(observation="fan described a shift")],
            ),
            relationship=_Dumpable(stage="recognition", trust=0.2),
            strategy=SimpleNamespace(
                primary_act="acknowledge",
                secondary_act="learn",
                should_ask_question=False,
                used_callback_ids=[],
            ),
            delivery=_Dumpable(length="short", energy="low"),
            candidates=[candidate],
        )
        return SimpleNamespace(
            plan=plan,
            selected_message=candidate.message,
            selection_mode="model_candidate",
            requires_operator_review=False,
            rejection_codes=(),
            degradation_codes=(),
            fallback_reason=None,
            model_calls=1,
            latency_ms=5,
            estimated_cost=0.00001,
            prompt_tokens=100,
            completion_tokens=20,
        )


class _MessageStore:
    def get_recent_creator_messages(self, creator_id, limit):
        return []


def test_tiffany_training_release_ingests_atomically_and_drives_shadow_retrieval():
    payload = load_compiled_corpus(ARTIFACT)
    report = payload["validation_report"]
    assert report["parts_present"] == ["00", "01", "02", "04", "05", "06", "07", "08", "09", "10"]
    assert report["positive_examples"] == 100
    assert report["negative_examples"] == 100
    assert report["paired_examples"] == 100
    assert report["negative_positive_retrieval_violations"] == 0
    assert payload["runtime_manifest"]["approval"]["status"] == "owner_approved"

    engine = _engine()
    ingestor = CorpusIngestor(engine, creator_id="creator-tiffany")
    first = ingestor.ingest(payload)
    second = ingestor.ingest(payload)
    assert first["cached"] is False
    assert second["cached"] is True
    assert first["status"] == "shadow"
    assert first["documents"] == 10
    assert first["examples"] == 100

    knowledge = KnowledgeRepository(engine, creator_id="creator-tiffany")
    live_retrieval = knowledge.retrieve(
        query="i had a long work shift and i'm tired",
        relationship_stage="recognition",
        scenario="share_work",
    )
    assert live_retrieval["release"] is None
    assert live_retrieval["rules"] == []
    assert live_retrieval["examples"] == []

    retrieved = knowledge.retrieve(
        query="i had a long work shift and i'm tired",
        relationship_stage="recognition",
        scenario="share_work",
        shadow=True,
    )
    assert retrieved["release"]["release_key"] == "tiffany-training-v1"
    assert retrieved["release"]["version"] == "1.0.0"
    assert retrieved["rules"]
    assert all(str(row.get("search_text") or "").strip() for row in retrieved["rules"])
    assert retrieved["examples"]
    assert all(row["good_response"] for row in retrieved["examples"])

    with engine.begin() as connection:
        _memory(connection, memory_type="identity_fact", value="works as a software engineer")
        _memory(connection, memory_type="preference", value="prefers concise replies")
        _memory(connection, memory_type="uncertain_hypothesis", value="might dislike questions")
    memory = MemoryRetrieverV3(engine, creator_id="creator-tiffany").retrieve(
        fan_id="fan-a",
        query="software work shift",
        now=datetime(2026, 8, 2, tzinfo=timezone.utc),
        shadow=True,
    )
    assert memory["policy_version"] == "part-09-v1"
    assert [row["type"] for row in memory["memories"]] == ["verified_personal_fact"]
    assert [row["category"] for row in memory["controls"]] == ["preference"]
    assert all(row["do_not_quote"] is True for row in memory["controls"])

    ConversationStateRepository(engine).ensure_conversation(
        "creator-tiffany", "fan-a", "chat-a"
    )
    inbound, created = MessageProcessingRepository(engine).insert_inbound(
        creator_id="creator-tiffany",
        platform_message_id="shadow-corpus-1",
        fan_id="fan-a",
        chat_id="chat-a",
        content="software work was a long shift",
        provider_created_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
    )
    assert created is True
    planner = _Planner()
    service = ConversationIntelligenceV3Service(
        engine=engine,
        creator_id="creator-tiffany",
        settings=V3RuntimeSettings(
            playbook_engine_mode="shadow",
            relationship_state_v2_mode="shadow",
            memory_retrieval_v3_mode="shadow",
            strategy_planner_v2_mode="shadow",
            global_diversity_mode="shadow",
            outcome_learning_mode="observe",
            multi_bubble_mode="shadow",
            allow_live_send=False,
        ),
        planner=planner,
        message_store=_MessageStore(),
        shadow_percent=100,
    )
    assert service.submit(
        inbound_id=inbound.id,
        inbound_message_id="shadow-corpus-1",
        fan_id="fan-a",
        trigger_kind="unread",
        provider_created_at=inbound.provider_created_at,
        current_decision_id=None,
        context={"fan_message": inbound.content, "history": ""},
    ) is True
    service.wait_for_idle()
    service.shutdown()

    assert planner.compiled.context["training_release"]["release_key"] == "tiffany-training-v1"
    assert planner.compiled.context["playbook_rules"]
    assert all(row["guidance"] for row in planner.compiled.context["playbook_rules"])
    assert planner.compiled.context["memory_controls"][0]["do_not_quote"] is True
    with engine.connect() as connection:
        outbox_count = connection.execute(select(func.count()).select_from(OUTBOX_MESSAGES)).scalar_one()
        runs = connection.execute(select(CONVERSATION_INTELLIGENCE_RUNS)).mappings().all()
        releases = connection.execute(select(CONVERSATION_CORPUS_RELEASES)).mappings().all()
    assert outbox_count == 0
    assert len(runs) == 1 and runs[0]["shadow"] is True
    assert runs[0]["versions"]["corpus"] == "tiffany-training-v1@1.0.0"
    assert len(releases) == 1 and releases[0]["status"] == "shadow"
