"""Fan session — wraps a funnel state machine with message history."""

from datetime import datetime, timezone

from src.funnel.state_machine import FunnelStateMachine


class FanSession:
    """Tracks a single fan's conversation, funnel stage, and message history."""

    def __init__(self, fan_id: str, creator_id: str) -> None:
        self.fan_id = fan_id
        self.creator_id = creator_id
        self.funnel = FunnelStateMachine()
        self.messages: list[dict] = []
        self.last_activity: datetime | None = None

    @property
    def message_count(self) -> int:
        """Total number of messages exchanged in this session."""
        return len(self.messages)

    def add_message(self, sender: str, content: str) -> None:
        """Append a message and bump last_activity + funnel counter."""
        self.messages.append({
            "sender": sender,
            "content": content,
            "timestamp": datetime.now(timezone.utc),
        })
        self.last_activity = datetime.now(timezone.utc)
        self.funnel.messages_in_stage += 1