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


def test_advanced_brain_receives_recent_creator_and_fan_turns():
    responder = MagicMock()
    responder.enabled = True
    responder.model = "deepseek-v4-flash"
    advanced = MagicMock()
    advanced.decide.return_value = _advanced_outcome("grounded reply")
    _, bot = _bot(
        bot_mode=BotMode.CONVERSATION,
        chat_responder=responder,
        advanced_brain_service=advanced,
        brain_settings_service=RuntimeSettings(_brain_settings()),
    )
    bot._approve_conversation_text = MagicMock(side_effect=lambda _, text: text)
    bot.message_store.save_message(
        "fan-a",
        "creator-a",
        "creator",
        "what class are you taking?",
        "creator-history-1",
    )
    bot.message_store.save_message(
        "fan-a",
        "creator-a",
        "fan",
        "history is my only summer course",
        "fan-history-1",
    )
    inbound, _ = bot.processing_repo.insert_inbound(
        creator_id="creator-a",
        platform_message_id="advanced-context-1",
        fan_id="fan-a",
        chat_id="chat-a",
        content="history is my only summer course",
        provider_created_at=datetime.now(timezone.utc),
    )

    bot._conversation_brain_reply(
        inbound_id=inbound.id,
        trigger_kind="unread",
        fan_id="fan-a",
        persona=bot.persona,
        history="Creator: what class are you taking?\nFan: history",
        fan_message="history is my only summer course",
        known_facts=[],
    )

    advanced_context = advanced.decide.call_args.kwargs["context"]
    assert advanced_context["recent_creator_messages"] == [
        "what class are you taking?"
    ]
    assert advanced_context["recent_fan_messages"] == [
        "history is my only summer course"
    ]


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


def test_both_advanced_and_current_failure_uses_policy_checked_safe_fallback():
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

    assert reply is not None
    assert reply.content == "tell me a little more?"
    stored = bot.conversation_decision_repo.get(
        inbound.id,
        creator_id="creator-a",
    )
    assert stored.authority == "current"
    assert stored.fallback_used is True
    assert stored.fallback_reason == "advanced_timeout"
    assert stored.gate_results["deterministic_safe_fallback"] == "approved"



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


def test_repeated_style_gate_rejection_is_repaired_without_another_model_call():
    responder = MagicMock()
    responder.enabled = True
    responder.model = "deepseek-v4-flash"
    responder.decide.return_value = _decision(
        "deepen",
        "specific_follow_up",
        "that's interesting babe, what part do you like most?",
        None,
    )
    advanced = MagicMock()
    advanced.decide.return_value = _advanced_outcome(
        "history sounds fun babe, what part do you like most?"
    )
    _, bot = _bot(
        bot_mode=BotMode.CONVERSATION,
        chat_responder=responder,
        advanced_brain_service=advanced,
        brain_settings_service=RuntimeSettings(_brain_settings()),
    )
    bot._approve_conversation_text = MagicMock(side_effect=lambda _, text: text)
    state = bot.brain_state_repo.get_or_create("creator-a", "fan-a")
    bot.brain_state_repo.update(
        creator_id="creator-a",
        fan_id="fan-a",
        expected_version=state["state_version"],
        changes={"question_streak": 2, "pet_name_streak": 2},
    )
    inbound, _ = bot.processing_repo.insert_inbound(
        creator_id="creator-a",
        platform_message_id="advanced-style-repair",
        fan_id="fan-a",
        chat_id="chat-a",
        content="history because it is my only summer course",
        provider_created_at=datetime.now(timezone.utc),
    )

    reply = bot._conversation_brain_reply(
        inbound_id=inbound.id,
        trigger_kind="unread",
        fan_id="fan-a",
        persona=bot.persona,
        history="Fan: history because it is my only summer course",
        fan_message="history because it is my only summer course",
        known_facts=[],
    )

    assert reply is not None
    assert "?" not in reply.content
    assert "babe" not in reply.content.casefold()
    assert responder.decide.call_count == 1
    stored = bot.conversation_decision_repo.get(
        inbound.id,
        creator_id="creator-a",
    )
    assert stored.fallback_used is True
    assert stored.repair_calls == 1
    assert stored.gate_results["deterministic_style_repair"] == "approved"


def test_semantic_repetition_is_regenerated_once_before_send():
    responder = MagicMock()
    responder.enabled = True
    responder.model = "deepseek-v4-flash"
    responder.decide.side_effect = [
        _decision(
            "maintain",
            "validation",
            "mm i'd hold u close again, just us right here",
            None,
        ),
        _decision(
            "play",
            "playful_challenge",
            "look at u stealing another kiss like that 😌",
            None,
        ),
    ]
    _, bot = _bot(
        bot_mode=BotMode.CONVERSATION,
        chat_responder=responder,
    )
    bot._approve_conversation_text = MagicMock(side_effect=lambda _, text: text)
    now = datetime.now(timezone.utc)
    bot.message_store.save_messages(
        [
            {
                "fan_id": "fan-a",
                "creator_id": "creator-a",
                "sender": "creator",
                "content": "mmm i'd hold u tighter, just us right here",
                "message_id": "creator-recent-1",
                "created_at": now,
            },
            {
                "fan_id": "fan-a",
                "creator_id": "creator-a",
                "sender": "creator",
                "content": "mm babe i'd hold u close and let the world fade away",
                "message_id": "creator-recent-2",
                "created_at": now,
            },
        ]
    )
    inbound, _ = bot.processing_repo.insert_inbound(
        creator_id="creator-a",
        platform_message_id="semantic-repeat-repair",
        fan_id="fan-a",
        chat_id="chat-a",
        content="-kiss-",
        provider_created_at=now,
    )

    reply = bot._conversation_brain_reply(
        inbound_id=inbound.id,
        trigger_kind="unread",
        fan_id="fan-a",
        persona=bot.persona,
        history="Fan: -kiss-",
        fan_message="-kiss-",
        known_facts=[],
    )

    assert reply is not None
    assert reply.content == "look at u stealing another kiss like that 😌"
    assert responder.decide.call_count == 2
    retry_context = responder.decide.call_args_list[1].kwargs
    assert "diversity_feedback" in retry_context
    assert "recent_creator_messages" in retry_context
    stored = bot.conversation_decision_repo.get(
        inbound.id,
        creator_id="creator-a",
    )
    assert stored.repair_calls == 1
    assert stored.gate_results["diversity_regeneration"] == "approved"


def test_second_semantically_repetitive_candidate_is_never_sent():
    responder = MagicMock()
    responder.enabled = True
    responder.model = "deepseek-v4-flash"
    responder.decide.side_effect = [
        _decision(
            "maintain",
            "validation",
            "mm i'd hold u close again, just us right here",
            None,
        ),
        _decision(
            "maintain",
            "validation",
            "mmm i'd hold u tighter again, just us right here",
            None,
        ),
    ]
    v3 = MagicMock()
    _, bot = _bot(
        bot_mode=BotMode.CONVERSATION,
        chat_responder=responder,
        conversation_intelligence_v3=v3,
    )
    bot._approve_conversation_text = MagicMock(side_effect=lambda _, text: text)
    now = datetime.now(timezone.utc)
    bot.message_store.save_message(
        "fan-a",
        "creator-a",
        "creator",
        "mm babe i'd hold u close, just us right here",
        "creator-recent-block",
        created_at=now,
    )
    inbound, _ = bot.processing_repo.insert_inbound(
        creator_id="creator-a",
        platform_message_id="semantic-repeat-block",
        fan_id="fan-a",
        chat_id="chat-a",
        content="-kiss-",
        provider_created_at=now,
    )

    reply = bot._conversation_brain_reply(
        inbound_id=inbound.id,
        trigger_kind="unread",
        fan_id="fan-a",
        source_message_id="semantic-repeat-block",
        source_timestamp=now,
        persona=bot.persona,
        history="Fan: -kiss-",
        fan_message="-kiss-",
        known_facts=[],
    )

    assert reply is None
    assert responder.decide.call_count == 2
    v3.submit.assert_called_once()
    assert v3.submit.call_args.kwargs["current_decision_id"] is None
    assert v3.submit.call_args.kwargs["inbound_message_id"] == (
        "semantic-repeat-block"
    )


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
