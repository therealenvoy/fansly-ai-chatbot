"""Script template models — parameterized templates with variable resolution."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ScriptCategory(str, Enum):
    """All supported script categories for the PPV funnel pipeline."""

    WELCOME = "welcome"
    PPV_SOFT_TEASE = "ppv_soft_tease"
    PPV_DIRECT = "ppv_direct"
    PPV_BUNDLE = "ppv_bundle"
    PPV_LIMITED_TIME = "ppv_limited_time"
    REENGAGE_3DAY = "reengage_3day"
    REENGAGE_7DAY = "reengage_7day"
    REENGAGE_14DAY = "reengage_14day"
    REENGAGE_30DAY = "reengage_30day"
    OBJECTION_PRICE = "objection_price"
    OBJECTION_FREE = "objection_free"
    OBJECTION_HESITATE = "objection_hesitate"
    OBJECTION_ALREADY_BOUGHT = "objection_already_bought"
    CUSTOM_INTAKE = "custom_intake"
    CUSTOM_UPSELL = "custom_upsell"
    CUSTOM_DELIVERY = "custom_delivery"


class ScriptVariable(BaseModel):
    """A named variable whose value is resolved from a context dict via dot-path.

    Attributes:
        name: The variable placeholder name (used as {name} in message templates).
        source: Dot-path into the context dict (e.g. "fan_notes.display_name").
        fallback: Value returned when the dot-path cannot be walked.
    """

    name: str
    source: str
    fallback: str = ""

    def resolve(self, context: dict[str, Any]) -> str:
        """Walk *source* dot-path through *context* and return the string value.

        Returns *fallback* if any segment is missing or if the walked value is
        not a dict on intermediate steps.
        """
        parts = self.source.split(".")
        current: Any = context
        for part in parts:
            if not isinstance(current, dict):
                return self.fallback
            if part not in current:
                return self.fallback
            current = current[part]
        return str(current)


class ScriptTemplate(BaseModel):
    """A parameterized script containing message templates with {variable} placeholders.

    Attributes:
        name: Unique identifier for this script template.
        category: Which ScriptCategory this template belongs to.
        description: Human-readable description of when this script is used.
        messages: The script messages with {variable_name} placeholders.
        variables: ScriptVariable definitions used to resolve placeholders.
        conditions: Dict of conditions that must pass (e.g. {"min_rapport_messages": 2}).
    """

    name: str
    category: ScriptCategory
    description: str
    messages: list[str]
    variables: list[ScriptVariable] = Field(default_factory=list)
    conditions: dict[str, Any] = Field(default_factory=dict)