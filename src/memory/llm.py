"""LLM-powered fact extraction from fan messages.

Uses DeepSeek (OpenAI-compatible API) to pull structured facts out of
what a fan says: name, occupation, interests, boundaries, personal details.
Gracefully degrades to a no-op when no API key is configured.
"""

import json
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """You extract facts about a fan from their chat messages to a content creator.
Return ONLY valid JSON, no markdown, no explanation.

Extract these fields (omit any you can't determine):
- "display_name": their name if stated (string)
- "occupation": their job if stated or clearly implied (string)
- "preferences": list of interests, hobbies, or content preferences they mention
- "emotional_triggers": list of things they respond strongly to (compliments, specific topics)
- "hard_limits": list of boundaries or things they explicitly don't want
- "facts": list of other personal details worth remembering (location, pets, schedule, life events, things they told you about themselves)

Be conservative — only extract what's actually stated or strongly implied.

Messages:
{messages}

JSON:"""


class LLMFactExtractor:
    """Extracts structured fan facts from messages via DeepSeek."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "deepseek-chat",
        base_url: str = "https://api.deepseek.com",
        timeout: float = 30.0,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def extract(self, messages: list[str]) -> dict:
        """Extract facts from a batch of fan messages.

        Returns dict with optional keys: display_name, occupation,
        preferences, emotional_triggers, hard_limits, facts.
        Returns empty dict on any failure or when disabled.
        """
        if not self.enabled:
            return {}

        if not messages:
            return {}

        transcript = "\n".join(f"- {m}" for m in messages if m and m.strip())
        if not transcript:
            return {}

        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "user", "content": EXTRACTION_PROMPT.format(messages=transcript)}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 500,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"].strip()

            # Strip markdown fences if the model wraps in ```
            if content.startswith("```"):
                content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            parsed = json.loads(content)
            if not isinstance(parsed, dict):
                return {}

            # Normalize: only keep known keys with proper types
            result = {}
            if isinstance(parsed.get("display_name"), str):
                result["display_name"] = parsed["display_name"]
            if isinstance(parsed.get("occupation"), str):
                result["occupation"] = parsed["occupation"]
            for key in ("preferences", "emotional_triggers", "hard_limits", "facts"):
                val = parsed.get(key)
                if isinstance(val, list):
                    result[key] = [str(v) for v in val if v]
            return result

        except Exception as e:
            logger.warning(f"Fact extraction failed: {e}")
            return {}
