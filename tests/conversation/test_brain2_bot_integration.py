from datetime import datetime, timezone
from unittest.mock import MagicMock

from src.conversation.brain import ConversationDecision
from src.conversation.mode import BotMode
from tests.persistence.test_message_pipeline import _bot


def _decision(objective, tactic, message, thread):
    return ConversationDecision(
        fan_state="engaged",
        state_summary="Fan is engaged.",
        objective=objective,
        tactic=tactic,
        open_thread=thread,
        draft=message,
        critique=("specific",),
        final_message=message,
        confidence=0.8,
    )


def test_live_brain_retrieves_previous_decision_and_updates_durable_state():
    responder = MagicMock()
    responder.enabled = True
    responder.model = "deepseek-v4-flash"
    responder.decide.side_effect = [
        _decision("support", "validation", "i hear you", "night shift"),
        _decision("deepen", "callback", "how did it go?", "night shift"),
    ]
    _, bot = _bot(
        bot_mode=BotMode.CONVERSATION,
        chat_responder=responder,
    )
    bot._approve_conversation_text = MagicMock(side_effect=lambda _, text: text)
    now = datetime.now(timezone.utc)
    first, _ = bot.processing_repo.insert_inbound(
        creator_id="creator-a",
        platform_message_id="m-1",
        fan_id="fan-a",
        chat_id="chat-a",
        content="rough shift",
        provider_created_at=now,
    )
    second, _ = bot.processing_repo.insert_inbound(
        creator_id="creator-a",
        platform_message_id="m-2",
        fan_id="fan-a",
        chat_id="chat-a",
        content="finally done",
        provider_created_at=now,
    )
    context = {
        "persona": bot.persona,
        "history": "",
        "fan_message": "rough shift",
        "known_facts": [],
    }

    assert bot._conversation_brain_reply(
        inbound_id=first.id,
        trigger_kind="unread",
        fan_id="fan-a",
        **context,
    ) is not None
    context["fan_message"] = "finally done"
    assert bot._conversation_brain_reply(
        inbound_id=second.id,
        trigger_kind="unread",
        fan_id="fan-a",
        **context,
    ) is not None

    second_context = responder.decide.call_args_list[1].kwargs
    assert second_context["previous_decision"] == {
        "objective": "support",
        "tactic": "validation",
        "open_thread": "night shift",
    }
    state = bot.brain_state_repo.get_or_create("creator-a", "fan-a")
    assert state["current_objective"] == "deepen"
    assert state["recent_objectives"] == ["deepen", "support"]
    assert state["question_streak"] == 1
    assert state["relationship_stage"] == "developing"
    assert state["current_mood"] == "engaged"
    assert state["last_fan_energy"] == "low"
    assert state["last_creator_energy"] == "low"


def test_generation_failure_uses_policy_checked_natural_fallback():
    responder = MagicMock()
    responder.enabled = True
    responder.model = "deepseek-v4-flash"
    responder.decide.return_value = None
    _, bot = _bot(
        bot_mode=BotMode.CONVERSATION,
        chat_responder=responder,
    )
    bot._approve_conversation_text = MagicMock(side_effect=lambda _, text: text)
    inbound, _ = bot.processing_repo.insert_inbound(
        creator_id="creator-a",
        platform_message_id="m-fallback",
        fan_id="fan-a",
        chat_id="chat-a",
        content="hard day",
        provider_created_at=datetime.now(timezone.utc),
    )

    reply = bot._conversation_brain_reply(
        inbound_id=inbound.id,
        trigger_kind="unread",
        fan_id="fan-a",
        persona=bot.persona,
        history="",
        fan_message="hard day",
        known_facts=[],
    )

    assert reply is not None
    assert reply.content == "tell me a little more?"
