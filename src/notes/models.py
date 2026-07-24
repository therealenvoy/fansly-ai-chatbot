"""FanNote Pydantic model — persistent fan notes with preferences, purchase history, and emotional triggers."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class FanNote(BaseModel):
    """Persistent note tracking a fan's preferences, purchase history, and emotional triggers."""

    fan_id: str
    creator_id: str
    display_name: Optional[str] = None
    preferences: list[str] = Field(default_factory=list)
    occupation: Optional[str] = None
    total_spent: float = Field(default=0.0)
    purchase_count: int = Field(default=0)
    last_purchase_at: Optional[datetime] = None
    emotional_triggers: list[str] = Field(default_factory=list)
    hard_limits: list[str] = Field(default_factory=list)
    notes: str = Field(default="")
    first_contact_at: Optional[datetime] = None
    relationship_stage: str = Field(default="new")

    @property
    def spend_tier(self) -> str:
        """Categorize fan by spending: 'whale' (>=500), 'average' (>=50), 'time_waster' (<50)."""
        if self.total_spent >= 500:
            return "whale"
        elif self.total_spent >= 50:
            return "average"
        else:
            return "time_waster"