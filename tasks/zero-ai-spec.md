# Spec: Zero-AI-Trace Chatting System

## Objective

Make every outbound bot message indistinguishable from a top 0.000001% human chatter. Zero detectable AI writing patterns. Messages must pass the "is this AI?" test when read by a savvy human.

Success criteria:
- No message contains ANY of the 33 known AI writing tells from the humanizer skill
- No two messages to the same fan use the same phrasing
- Style mirror captures 8+ dimensions of fan writing (up from 5)
- All hardcoded templates are replaced with variation pools (5-8 variants each)
- Every message flows through humanizer → style mirror → persona validation pipeline

## Tech Stack

- Python 3.11
- pytest for TDD
- Existing project structure under /opt/data/fansly-ai-chatbot/

## Commands

- Test: `cd /opt/data/fansly-ai-chatbot && python -m pytest tests/humanize/ -v`
- Full suite: `cd /opt/data/fansly-ai-chatbot && python -m pytest tests/ -q`
- Run bot: `cd /opt/data/fansly-ai-chatbot && python -m src.main`

## Project Structure (additions)

```
src/humanize/           ← NEW: humanizer post-processing system
├── __init__.py
├── filter.py           ← Main pipeline: detects + removes all 33 AI tells
├── patterns.py         ← Regex patterns for each AI tell
└── variation.py        ← Variation pool engine for eliminating repetition

tests/humanize/         ← NEW: TDD tests for humanizer
├── __init__.py
├── test_filter.py      ← Tests for each of the 33 patterns
└── test_variation.py   ← Tests for variation engine

src/style/
└── mirror.py           ← ENHANCED: add punctuation, sentence variance, greeting transforms
```

## Code Style

```python
# Every filter function: takes str, returns str
class HumanizerFilter:
    """Pipeline of pattern-removing transforms. Order matters."""

    def __init__(self):
        self.transforms: list[Callable[[str], str]] = [
            self._remove_em_dashes,
            self._compress_filler_phrases,
            self._remove_ai_vocabulary,
            # ...
        ]

    def humanize(self, text: str) -> str:
        for transform in self.transforms:
            text = transform(text)
        return text

    def _remove_em_dashes(self, text: str) -> str:
        return text.replace("—", ", ").replace("–", ", ")
```

## Boundaries

- Always: TDD (RED → GREEN), every new pattern needs a test, run full suite before deploy
- Ask first: adding new dependencies, changing existing message flow in bot.py
- Never: remove existing tests, skip RED step, hardcode the same phrase twice

## Open Questions

- Should humanizer run BEFORE or AFTER style mirror? (Decision: humanizer FIRST to clean AI tells, then style mirror adapts to fan — mirror should adapt the final humanized text, not re-introduce AI patterns)