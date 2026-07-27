import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import httpx

from src.conversation.brain import ConversationDecision
from src.conversation.llm import DeepSeekChatResponder
from src.conversation.repository import ConversationDecisionRepository
from src.persistence.database import create_database_engine
from src.persistence.pipeline import MessageProcessingRepository
from src.persistence.schema import metadata
from src.persistence.state import ConversationStateRepository
from src.persona.models import PersonaDocument


def _persona():
    return PersonaDocument(
        creator_id="creator-a",
        tone="warm",
        signature_phrases=[],
        forbidden_phrases=[],
        emoji_style="light",
        sentence_style="short",
        pet_names=["babe"],
        content_boundaries=["No meetups"],
        sample_winning_messages=[],
        response_length_target=35,
    )


def _decision(message="how was work?"):
    return {
        "fan_state": "engaged",
        "state_summary": "Fan is engaged.",
        "objective": "deepen",
        "tactic": "callback",
        "open_thread": "night shift",
        "draft": message,
        "critique": ["specific"],
        "final_message": message,
        "confidence": 0.8,
    }


def test_output_budget_is_configurable_and_previous_decision_is_in_context(
    monkeypatch,
):
    response = MagicMock(spec=httpx.Response)
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "choices": [{"message": {"content": json.dumps(_decision())}}]
    }
    post = MagicMock(return_value=response)
    monkeypatch.setattr(httpx, "post", post)

    responder = DeepSeekChatResponder(
        "secret",
        max_output_tokens=900,
        json_repair_attempts=1,
    )
    result = responder.decide(
        persona=_persona(),
        history="Creator: hope work went okay",
        fan_message="finally done",
        known_facts=[],
        previous_decision={
            "objective": "support",
            "tactic": "validation",
            "open_thread": "night shift",
        },
        recent_objectives=["support", "support"],
        recent_tactics=["validation", "validation"],
    )

    assert result is not None
    payload = post.call_args.kwargs["json"]
    assert payload["max_tokens"] == 900
    user = payload["messages"][1]["content"]
    assert "Previous objective: support" in user
    assert "Unresolved open thread: night shift" in user
    assert "Recent tactics: validation, validation" in user


def test_malformed_json_gets_exactly_one_bounded_repair(monkeypatch):
    malformed = MagicMock(spec=httpx.Response)
    malformed.raise_for_status.return_value = None
    malformed.json.return_value = {
        "choices": [{"message": {"content": '{"fan_state":"engaged"'}}]
    }
    repaired = MagicMock(spec=httpx.Response)
    repaired.raise_for_status.return_value = None
    repaired.json.return_value = {
        "choices": [{"message": {"content": json.dumps(_decision())}}]
    }
    post = MagicMock(side_effect=[malformed, repaired])
    monkeypatch.setattr(httpx, "post", post)

    result = DeepSeekChatResponder(
        "secret",
        json_repair_attempts=1,
    ).decide(
        persona=_persona(),
        history="",
        fan_message="hey",
        known_facts=[],
    )

    assert result is not None
    assert post.call_count == 2
    repair = post.call_args_list[1].kwargs["json"]
    assert repair["temperature"] == 0
    assert "Repair the malformed JSON" in repair["messages"][0]["content"]


def test_failed_repair_stops_after_one_attempt(monkeypatch):
    response = MagicMock(spec=httpx.Response)
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "choices": [{"message": {"content": '{"final_message":'}}]
    }
    post = MagicMock(return_value=response)
    monkeypatch.setattr(httpx, "post", post)

    result = DeepSeekChatResponder(
        "secret",
        json_repair_attempts=1,
    ).decide(
        persona=_persona(),
        history="",
        fan_message="hey",
        known_facts=[],
    )

    assert result is None
    assert post.call_count == 2


def test_repository_reads_latest_decisions_for_only_requested_fan():
    engine = create_database_engine(
        "sqlite:///:memory:",
        environment={"APP_ENV": "test"},
    )
    metadata.create_all(engine)
    state = ConversationStateRepository(engine)
    pipeline = MessageProcessingRepository(engine)
    repository = ConversationDecisionRepository(engine)
    now = datetime.now(timezone.utc)
    decision = ConversationDecision.from_model_output(
        json.dumps(_decision()),
        proactive_kind=None,
    )
    assert decision is not None

    for number, fan_id in enumerate(("fan-a", "fan-b", "fan-a"), 1):
        state.ensure_conversation("creator-a", fan_id, f"chat-{fan_id}")
        inbound, _ = pipeline.insert_inbound(
            creator_id="creator-a",
            platform_message_id=f"message-{number}",
            fan_id=fan_id,
            chat_id=f"chat-{fan_id}",
            content="hey",
            provider_created_at=now,
        )
        repository.save(
            inbound_message_id=inbound.id,
            creator_id="creator-a",
            fan_id=fan_id,
            trigger_kind="unread",
            decision=decision.with_approved_message(f"reply-{number}"),
            model="deepseek-v4-flash",
        )

    recent = repository.latest_for_fan(
        creator_id="creator-a",
        fan_id="fan-a",
        limit=2,
    )

    assert [item.decision.final_message for item in recent] == [
        "reply-3",
        "reply-1",
    ]


def test_incomplete_json_contract_gets_one_schema_repair(monkeypatch):
    incomplete = MagicMock(spec=httpx.Response)
    incomplete.raise_for_status.return_value = None
    incomplete.json.return_value = {
        "choices": [{"message": {"content": json.dumps({"final_message": "hey"})}}]
    }
    repaired = MagicMock(spec=httpx.Response)
    repaired.raise_for_status.return_value = None
    repaired.json.return_value = {
        "choices": [{"message": {"content": json.dumps(_decision("hey"))}}]
    }
    post = MagicMock(side_effect=[incomplete, repaired])
    monkeypatch.setattr(httpx, "post", post)

    result = DeepSeekChatResponder("secret", json_repair_attempts=1).decide(
        persona=_persona(),
        history="",
        fan_message="hey",
        known_facts=[],
    )

    assert result is not None
    assert result.final_message == "hey"
    assert post.call_count == 2
