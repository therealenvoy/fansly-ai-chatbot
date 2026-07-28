"""Conversation-mode configuration and generation."""

from .mode import BotMode, ConversationPolicy

__all__ = ["BotMode", "ConversationPolicy", "DeepSeekChatResponder"]


def __getattr__(name):
    if name == "DeepSeekChatResponder":
        from .llm import DeepSeekChatResponder

        return DeepSeekChatResponder
    raise AttributeError(name)
