"""PersonaDocument — Pydantic model for creator voice configuration.

Every creator persona is defined by a YAML config validated against this model.
"""

from pydantic import BaseModel, Field


class PersonaDocument(BaseModel):
    """Voice consistency configuration for a single creator.

    Loaded from config/creators/{creator_id}.yaml at runtime.
    """

    creator_id: str
    tone: str
    signature_phrases: list[str]
    forbidden_phrases: list[str]
    common_typos: dict[str, str] = Field(default_factory=dict)
    emoji_style: str
    sentence_style: str
    pet_names: list[str] = Field(default_factory=list)
    content_boundaries: list[str] = Field(default_factory=list)
    sample_winning_messages: list[str] = Field(default_factory=list)
    voice_note_frequency: str = "occasional"
    response_length_target: int = 40