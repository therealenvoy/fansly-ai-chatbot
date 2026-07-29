from datetime import datetime, timezone
from unittest.mock import MagicMock

from src.conversation.advanced import AdvancedDecisionOutcome
from src.conversation.brain import ConversationDecision
from src.conversation.brain2 import BrainRuntimeSettings
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



class RuntimeSettings:
    def __init__(self, settings):
        self.settings = settings

    def snapshot(self):
        return self.settings


class SequencedRuntimeSettings:
    def __init__(self, *settings):
        self.settings = list(settings)

    def snapshot(self):
        if len(self.settings) > 1:
            return self.settings.pop(0)
        return self.settings[0]


def _advanced_outcome(message="advanced hello"):
    decision = _decision("maintain", "direct_answer", message, None)
    return AdvancedDecisionOutcome(
        decision=decision,
        succeeded=True,
        route="fast",
        model="deepseek-v4-flash",
        provider_attempts=1,
        model_calls=1,
    )


def _brain_settings(percent=100):
    return BrainRuntimeSettings(
        mode="advanced",
        allow_advanced_send=True,
        live_percent=percent,
        max_live_percent=100,
    )


def test_advanced_authority_uses_advanced_decision_and_skips_current_generator():
    responder = MagicMock()
    responder.enabled = True
    responder.model = "deepseek-v4-flash"
    advanced = MagicMock()
    advanced.decide.return_value = _advanced_outcome()
    _, bot = _bot(
        bot_mode=BotMode.CONVERSATION,
        chat_responder=responder,
        advanced_brain_service=advanced,
        brain_settings_service=RuntimeSettings(_brain_settings()),
    )
    bot._approve_conversation_text = MagicMock(side_effect=lambda _, text: text)
    inbound, _ = bot.processing_repo.insert_inbound(
        creator_id="creator-a",
        platform_message_id="advanced-1",
        fan_id="fan-a",
        chat_id="chat-a",
        content="hey",
        provider_created_at=datetime.now(timezone.utc),
    )

    reply = bot._conversation_brain_reply(
        inbound_id=inbound.id,
        trigger_kind="unread",
        fan_id="fan-a",
        persona=bot.persona,
        history="Fan: hey",
        fan_message="hey",
        known_facts=[],
    )

    assert reply.content == "advanced hello"
    advanced.decide.assert_called_once()
    responder.decide.assert_not_called()
    stored = bot.conversation_decision_repo.get(
        inbound.id,
        creator_id="creator-a",
    )
    assert stored.authority == "advanced"


def test_rollback_after_generation_falls_back_before_advanced_decision_is_saved():
    responder = MagicMock()
    responder.enabled = True
    responder.model = "deepseek-v4-flash"
    responder.decide.return_value = _decision(
        "maintain", "direct_answer", "current after rollback", None
    )
    advanced = MagicMock()
    advanced.decide.return_value = _advanced_outcome()
    settings = SequencedRuntimeSettings(
        _brain_settings(),
        BrainRuntimeSettings(mode="current"),
    )
    _, bot = _bot(
        bot_mode=BotMode.CONVERSATION,
        chat_responder=responder,
        advanced_brain_service=advanced,
        brain_settings_service=settings,
    )
    bot._approve_conversation_text = MagicMock(side_effect=lambda _, text: text)
    inbound, _ = bot.processing_repo.insert_inbound(
        creator_id="creator-a",
        platform_message_id="advanced-rollback-race",
        fan_id="fan-a",
        chat_id="chat-a",
        content="hey",
        provider_created_at=datetime.now(timezone.utc),
    )

    reply = bot._conversation_brain_reply(
        inbound_id=inbound.id,
        trigger_kind="unread",
        fan_id="fan-a",
        persona=bot.persona,
        history="Fan: hey",
        fan_message="hey",
        known_facts=[],
    )

    assert reply.content == "current after rollback"
    stored = bot.conversation_decision_repo.get(
        inbound.id,
        creator_id="creator-a",
    )
    assert stored.authority == "current"
    assert stored.fallback_reason == "stale_authority_after_generation"


def test_advanced_failure_falls_back_to_current_generator_once():
    responder = MagicMock()
    responder.enabled = True
    responder.model = "deepseek-v4-flash"
    responder.decide.return_value = _decision(
        "maintain", "direct_answer", "current fallback", None
    )
    advanced = MagicMock()
    advanced.decide.return_value = AdvancedDecisionOutcome(
        decision=None,
        succeeded=False,
        route="fast",
        model="deepseek-v4-flash",
        fallback_reason="fast_json_invalid",
    )
    _, bot = _bot(
        bot_mode=BotMode.CONVERSATION,
        chat_responder=responder,
        advanced_brain_service=advanced,
        brain_settings_service=RuntimeSettings(_brain_settings()),
    )
    bot._approve_conversation_text = MagicMock(side_effect=lambda _, text: text)
    inbound, _ = bot.processing_repo.insert_inbound(
        creator_id="creator-a",
        platform_message_id="advanced-fallback",
        fan_id="fan-a",
        chat_id="chat-a",
        content="hey",
        provider_created_at=datetime.now(timezone.utc),
    )

    reply = bot._conversation_brain_reply(
        inbound_id=inbound.id,
        trigger_kind="unread",
        fan_id="fan-a",
        persona=bot.persona,
        history="Fan: hey",
        fan_message="hey",
        known_facts=[],
    )

    assert reply.content == "current fallback"
    assert responder.decide.call_count == 1
    stored = bot.conversation_decision_repo.get(
        inbound.id,
        creator_id="creator-a",
    )
    assert stored.authority == "current"
    assert stored.fallback_used is True
    assert stored.fallback_reason == "fast_json_invalid"


def test_both_advanced_and_current_failure_preserves_retryable_inbound():
    responder = MagicMock()
    responder.enabled = True
    responder.model = "deepseek-v4-flash"
    responder.decide.return_value = None
    advanced = MagicMock()
    advanced.decide.return_value = AdvancedDecisionOutcome(
        decision=None,
        succeeded=False,
        route="fast",
        model="deepseek-v4-flash",
        fallback_reason="advanced_timeout",
    )
    _, bot = _bot(
        bot_mode=BotMode.CONVERSATION,
        chat_responder=responder,
        advanced_brain_service=advanced,
        brain_settings_service=RuntimeSettings(_brain_settings()),
    )
    inbound, _ = bot.processing_repo.insert_inbound(
        creator_id="creator-a",
        platform_message_id="both-fail",
        fan_id="fan-a",
        chat_id="chat-a",
        content="hey",
        provider_created_at=datetime.now(timezone.utc),
    )

    reply = bot._conversation_brain_reply(
        inbound_id=inbound.id,
        trigger_kind="unread",
        fan_id="fan-a",
        persona=bot.persona,
        history="Fan: hey",
        fan_message="hey",
        known_facts=[],
    )

    assert reply is None



def test_advanced_post_generation_gate_rejection_falls_back_to_current():
    responder = MagicMock()
    responder.enabled = True
    responder.model = "deepseek-v4-flash"
    responder.decide.return_value = _decision(
        "maintain", "direct_answer", "safe current reply", None
    )
    advanced = MagicMock()
    advanced.decide.return_value = _advanced_outcome("unlock this for $20")
    _, bot = _bot(
        bot_mode=BotMode.CONVERSATION,
        chat_responder=responder,
        advanced_brain_service=advanced,
        brain_settings_service=RuntimeSettings(_brain_settings()),
    )
    bot._approve_conversation_text = MagicMock(side_effect=lambda _, text: text)
    inbound, _ = bot.processing_repo.insert_inbound(
        creator_id="creator-a",
        platform_message_id="advanced-gate-fallback",
        fan_id="fan-a",
        chat_id="chat-a",
        content="hey",
        provider_created_at=datetime.now(timezone.utc),
    )

    reply = bot._conversation_brain_reply(
        inbound_id=inbound.id,
        trigger_kind="unread",
        fan_id="fan-a",
        persona=bot.persona,
        history="Fan: hey",
        fan_message="hey",
        known_facts=[],
    )

    assert reply.content == "safe current reply"
    assert responder.decide.call_count == 1
    stored = bot.conversation_decision_repo.get(
        inbound.id,
        creator_id="creator-a",
    )
    assert stored.authority == "current"
    assert stored.fallback_reason == "advanced_quality_gate_rejected"


def test_human_delivery_compiles_live_context_and_styles_approved_reply():
    responder = MagicMock()
    responder.enabled = True
    responder.model = "deepseek-v4-flash"
    responder.decide.return_value = _decision(
        "maintain",
        "direct_answer",
        "That Actually Made Me Smile",
        None,
    )
    human_delivery = MagicMock()
    human_delivery.compile_live_context.return_value = {
        "chat_instructions": "compiled human guide",
        "brand_bible": "",
        "compilation": {"included": ["creator_persona"]},
    }
    human_delivery.apply_live_style.return_value = {
        "content": "that actually made me smile",
        "applied": True,
        "reason": "live_style",
    }
    _, bot = _bot(
        bot_mode=BotMode.CONVERSATION,
        chat_responder=responder,
        human_delivery=human_delivery,
    )
    bot._approve_conversation_text = MagicMock(side_effect=lambda _, text: text)
    inbound, _ = bot.processing_repo.insert_inbound(
        creator_id="creator-a",
        platform_message_id="human-delivery-live",
        fan_id="fan-a",
        chat_id="chat-a",
        content="hey",
        provider_created_at=datetime.now(timezone.utc),
    )

    reply = bot._conversation_brain_reply(
        inbound_id=inbound.id,
        trigger_kind="unread",
        fan_id="fan-a",
        persona=bot.persona,
        history="Fan: hey",
        fan_message="hey",
        known_facts=[],
        chat_instructions="legacy guide",
        brand_bible="legacy brand",
    )

    assert reply.content == "that actually made me smile"
    call_context = responder.decide.call_args.kwargs
    assert call_context["chat_instructions"] == "compiled human guide"
    assert call_context["brand_bible"] == ""
    human_delivery.compile_live_context.assert_called_once()
    human_delivery.apply_live_style.assert_called_once()
