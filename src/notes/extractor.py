"""NoteExtractor — LLM-based extraction and merge logic for fan notes."""

from typing import Any, Callable
from src.notes.models import FanNote


class NoteExtractor:
    """Extract preferences, triggers, and details from conversation messages using an LLM.
    
    Accepts any callable as llm_client for easy mocking/testing.
    """

    def __init__(self, llm_client: Callable[..., Any]):
        self.llm_client = llm_client

    async def extract(self, message: str) -> dict:
        """Extract structured details from a message using the LLM client.
        
        Returns a dict with optional keys like preferences, occupation,
        emotional_triggers, hard_limits, display_name, etc.
        """
        result = await self.llm_client(message)
        return result

    def merge(self, note: FanNote, extracted: dict) -> FanNote:
        """Merge extracted details into an existing FanNote.
        
        Rules:
        - display_name: only set if currently None (first-seen wins)
        - preferences, emotional_triggers, hard_limits: append new unique values
        - occupation: set if currently None
        - All other fields on the note are preserved as-is
        """
        # display_name: first-seen wins
        if note.display_name is None and extracted.get("display_name"):
            note.display_name = extracted["display_name"]

        # occupation: fill if empty
        if note.occupation is None and extracted.get("occupation"):
            note.occupation = extracted["occupation"]

        # Append unique values to list fields
        for field_name in ["preferences", "emotional_triggers", "hard_limits", "facts"]:
            new_items = extracted.get(field_name, [])
            if new_items:
                existing = list(getattr(note, field_name, []))
                for item in new_items:
                    if item not in existing:
                        existing.append(item)
                setattr(note, field_name, existing)

        return note