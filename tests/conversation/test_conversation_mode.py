import json
from unittest.mock import MagicMock

import httpx

from src.conversation.llm import DeepSeekChatResponder
from src.conversation.mode import BotMode, ConversationPolicy
from src.persona.models import PersonaDocument


def _persona():
    return PersonaDocument(
        creator_id="creator-a",
        tone="warm",
        signature_phrases=["hey babe"],
        forbidden_phrases=["bro"],
        emoji_style="light",
        sentence_style="short",
        pet_names=["babe"],
        content_boundaries=["No meetups"],
        sample_winning_messages=["hey, how was ur night?"],
        response_length_target=35,
    )


def test_bot_mode_rejects_unknown_values():
    try:
        BotMode.parse("blast_everyone")
    except ValueError as error:
        assert "conversation" in str(error)
        assert "full_ppv" in str(error)
    else:
        raise AssertionError("unknown mode was accepted")


def test_conversation_policy_blocks_sales_but_allows_normal_chat():
    policy = ConversationPolicy()

    assert policy.sales_reason("hey babe how was ur day?") is None
    assert policy.sales_reason("unlock this PPV for $20") is not None
    assert policy.sales_reason("tip me to see the video") is not None
    assert policy.sales_reason("I made something new for you, wanna see?") is not None


def test_deepseek_responder_uses_context_and_returns_message(monkeypatch):
    response = MagicMock(spec=httpx.Response)
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "choices": [{"message": {"content": " hey babe, how was work? "}}]
    }
    post = MagicMock(return_value=response)
    monkeypatch.setattr(httpx, "post", post)
    responder = DeepSeekChatResponder("secret")

    result = responder.respond(
        persona=_persona(),
        history="Fan: long day at work",
        fan_message="finally home",
        known_facts=["works nights"],
        display_name="Sam",
        chat_instructions="Answer directly, then ask one question.",
        brand_bible="Sunny is playful, attentive, and never formal.",
    )

    assert result == "hey babe, how was work?"
    payload = post.call_args.kwargs["json"]
    assert payload["model"] == "deepseek-v4-flash"
    assert payload["thinking"] == {"type": "disabled"}
    system = payload["messages"][0]["content"]
    user = payload["messages"][1]["content"]
    assert "conversation-only" in system
    assert "Sunny is playful, attentive, and never formal." in system
    assert "Answer directly, then ask one question." in system
    assert "hey, how was ur night?" in system
    assert system.index("NON-NEGOTIABLE RUNTIME RULES") < system.index(
        "CREATOR CHATTING INSTRUCTIONS"
    )
    assert system.index("CREATOR CHATTING INSTRUCTIONS") < system.index(
        "CREATOR BRAND BIBLE"
    )
    assert system.index("CREATOR BRAND BIBLE") < system.index(
        "CREATOR PERSONA"
    )
    assert "finally home" in payload["messages"][1]["content"]
    assert "Known fact: works nights" not in user
    assert "- works nights" in user


def test_deepseek_responder_keeps_instructions_beyond_20k(monkeypatch):
    response = MagicMock(spec=httpx.Response)
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "choices": [{"message": {"content": "got u babe"}}]
    }
    post = MagicMock(return_value=response)
    monkeypatch.setattr(httpx, "post", post)
    marker = "instruction-after-twenty-thousand"

    result = DeepSeekChatResponder("secret").respond(
        persona=_persona(),
        history="Fan: hey",
        fan_message="hey",
        known_facts=[],
        chat_instructions=("x" * 25_000) + marker,
    )

    assert result == "got u babe"
    system = post.call_args.kwargs["json"]["messages"][0]["content"]
    assert marker in system


def test_stalled_responder_continues_without_calling_out_inactivity(
    monkeypatch,
):
    response = MagicMock(spec=httpx.Response)
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "choices": [{"message": {"content": "how did your shift go babe?"}}]
    }
    post = MagicMock(return_value=response)
    monkeypatch.setattr(httpx, "post", post)

    result = DeepSeekChatResponder("secret").respond(
        persona=_persona(),
        history="Fan: working late\nCreator: hope it goes smoothly babe",
        fan_message=None,
        known_facts=["works nights"],
        proactive=True,
        proactive_kind="stalled",
    )

    assert result == "how did your shift go babe?"
    task = post.call_args.kwargs["json"]["messages"][1]["content"]
    assert "Continue this existing conversation naturally" in task
    assert "Never mention inactivity" in task
    assert "Do not repeat the creator's last message" in task


def test_deepseek_decide_returns_plan_draft_critique_and_final(
    monkeypatch,
):
    response = MagicMock(spec=httpx.Response)
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "fan_state": "engaged",
                            "state_summary": "Fan just finished work.",
                            "objective": "deepen",
                            "tactic": "callback",
                            "open_thread": "night shift",
                            "draft": "how was work?",
                            "critique": [
                                "Use the saved night-shift detail",
                            ],
                            "final_message": (
                                "did the night shift treat u any better today?"
                            ),
                            "confidence": 0.86,
                        }
                    )
                }
            }
        ]
    }
    post = MagicMock(return_value=response)
    monkeypatch.setattr(httpx, "post", post)

    decision = DeepSeekChatResponder("secret").decide(
        persona=_persona(),
        history="Fan: finally home",
        fan_message="long shift",
        known_facts=["works nights"],
    )

    assert decision is not None
    assert decision.objective == "deepen"
    assert decision.tactic == "callback"
    assert decision.final_message == (
        "did the night shift treat u any better today?"
    )
    payload = post.call_args.kwargs["json"]
    assert "CONVERSATION-BRAIN OUTPUT" in (
        payload["messages"][0]["content"]
    )
    assert "critique the draft for specificity" in (
        payload["messages"][1]["content"]
    )
