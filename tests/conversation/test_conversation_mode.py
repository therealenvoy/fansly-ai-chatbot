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
    )

    assert result == "hey babe, how was work?"
    payload = post.call_args.kwargs["json"]
    assert payload["model"] == "deepseek-v4-flash"
    assert payload["thinking"] == {"type": "disabled"}
    assert "conversation-only" in payload["messages"][0]["content"]
    assert "finally home" in payload["messages"][1]["content"]
