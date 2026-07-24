# Fansly AI Chatbot — Complete 17-System Implementation Plan

> **For Hermes:** Use `subagent-driven-development` + `test-driven-development` skills to implement task-by-task. Two-stage review (spec compliance → code quality) after every task.

**Goal:** Build all 17 systems that the top 0.000001% OnlyFans/Fansly chatters use — persona engine, 5-stage funnel, script library, push-pull rhythm, NLP triggers, reciprocity engine, upsell ladders, aftercare, mass messaging, whale nurturing, churn prediction, analytics — into a single Python/FastAPI chatbot that maximizes PPV conversion.

**Architecture:** Modular Python backend (`src/` packages) with FastAPI endpoints, PostgreSQL persistence, ChromaDB vector memory, and LLM integration via OpenAI/Anthropic. Each system is a self-contained module with its own schema, service, and API routes. TDD enforced — every module ships with unit + integration tests.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy + PostgreSQL, ChromaDB, Pydantic v2, pytest, pytest-asyncio

**Current State:**
- `src/schema.py` — Message, Conversation, ConversationStage (4-stage SELL), PersonalityType (4 types)
- `src/emotion/` — empty
- `src/llm/` — empty
- `src/memory/` — empty
- `src/profiling/` — empty
- `requirements.txt` — torch, transformers, vaderSentiment, fastapi, chromadb, openai, anthropic, etc.

---

## IMPLEMENTATION ORDER (by dependency chain)

```
Phase 1 (Core): Schema → Persona → Funnel → Fan Notes
Phase 2 (Script Engine): Script Library → Fan Types → Push-Pull
Phase 3 (Sales): Delay System → Aftercare → Mass Messaging
Phase 4 (Psychology): NLP Triggers → Reciprocity → Objection Handling
Phase 5 (Lifecycle): Tier Classification → Whale Pipeline → Churn Prediction
Phase 6 (Analytics): KPI Dashboard → A/B Testing
```

---

## PHASE 1: CORE ENGINE

### Task 1: Upgrade Schema to 5-Stage Funnel + 5 Personality Types

**Objective:** Expand the current 4-stage SELL framework and 4 personality types to match the research — 5 stages (Rapport→Tease→Offer→Handle→Close) and 5 personality types (add Chatty Fan).

**Files:**
- Modify: `src/schema.py`
- Create: `tests/test_schema.py`

**Step 1: Write failing test**

```python
# tests/test_schema.py
import pytest
from src.schema import ConversationStage, PersonalityType, Message, Conversation

def test_five_conversation_stages_exist():
    """Verify all 5 stages from the research are present."""
    stages = [s.value for s in ConversationStage]
    assert "rapport" in stages
    assert "tease" in stages
    assert "offer" in stages
    assert "handle" in stages  # objection handling (was missing)
    assert "close" in stages

def test_five_personality_types_exist():
    """Verify all 5 types including Chatty Fan."""
    types = [t.value for t in PersonalityType]
    assert "instant_buyer" in types
    assert "quiet_lurker" in types
    assert "attention_seeker" in types
    assert "tester" in types
    assert "chatty_fan" in types  # NEW — was missing

def test_conversation_funnel_progression_valid():
    """Stages must progress forward, never backward."""
    valid_progression = [
        ConversationStage.RAPPORT,
        ConversationStage.TEASE,
        ConversationStage.OFFER,
        ConversationStage.HANDLE,
        ConversationStage.CLOSE,
    ]
    conv = Conversation(
        conversation_id="test_001",
        subscriber_id="sub_1",
        creator_id="creator_1",
        messages=[],
        stages_completed=valid_progression,
    )
    assert conv.stages_completed == valid_progression

def test_message_has_fan_archetype_tag():
    """Messages should support a fan archetype tag for personality routing."""
    msg = Message(
        timestamp="2026-01-01T00:00:00Z",
        sender="subscriber",
        content="Hey! Love your stuff",
        fan_archetype="chatty_fan",
    )
    assert msg.fan_archetype == "chatty_fan"
```

Run: `pytest tests/test_schema.py -v`
Expected: FAIL — old enum values, missing types

**Step 2: Implement updated schema**

```python
# src/schema.py — update enums
class ConversationStage(str, Enum):
    RAPPORT = "rapport"       # Building connection (2-6 exchanges)
    TEASE = "tease"           # Planting curiosity, one detail only
    OFFER = "offer"           # Name content + price after fan shows interest
    HANDLE = "handle"         # Work through 1-3 objections
    CLOSE = "close"           # One direct, confident send

class PersonalityType(str, Enum):
    INSTANT_BUYER = "instant_buyer"
    QUIET_LURKER = "quiet_lurker"
    ATTENTION_SEEKER = "attention_seeker"
    TESTER = "tester"
    CHATTY_FAN = "chatty_fan"  # NEW
```

**Step 3: Run tests to verify pass**

Run: `pytest tests/test_schema.py -v`
Expected: 4 PASS

**Step 4: Commit**

```bash
git add src/schema.py tests/test_schema.py
git commit -m "feat: upgrade schema to 5-stage funnel + 5 personality types"
```

---

### Task 2: Persona System — Voice Consistency Engine

**Objective:** Build a persona document loader + validator that enforces voice consistency across all bot responses. Every message goes through persona check before sending.

**Files:**
- Create: `src/persona/__init__.py`
- Create: `src/persona/models.py`
- Create: `src/persona/loader.py`
- Create: `src/persona/validator.py`
- Create: `tests/persona/test_models.py`
- Create: `tests/persona/test_loader.py`
- Create: `tests/persona/test_validator.py`
- Create: `config/creators/sunny_charm.yaml`

**Step 1: Write failing test for PersonaDocument model**

```python
# tests/persona/test_models.py
from src.persona.models import PersonaDocument

def test_persona_document_required_fields():
    doc = PersonaDocument(
        creator_id="sunny_charm",
        tone="flirty",
        signature_phrases=["hey babe", "missed you"],
        forbidden_phrases=["daddy", "what's up dude"],
        common_typos={"your": "ur", "you": "u"},
        emoji_style="moderate",
        sentence_style="short_punchy",
        pet_names=["babe", "sweetie", "handsome"],
        content_boundaries=["no meetups", "no personal socials"],
        sample_winning_messages=["msg1", "msg2"],
    )
    assert doc.creator_id == "sunny_charm"
    assert "daddy" in doc.forbidden_phrases
    assert doc.emoji_style == "moderate"
```

Run: `pytest tests/persona/test_models.py -v`
Expected: FAIL — module not found

**Step 2: Implement models**

```python
# src/persona/__init__.py (empty)
# src/persona/models.py
from pydantic import BaseModel
from typing import List, Optional

class PersonaDocument(BaseModel):
    creator_id: str
    tone: str  # flirty, girl_next_door, dominant, bratty, sweet
    signature_phrases: List[str]  # 10-15 phrases they always use
    forbidden_phrases: List[str]  # 5+ phrases they'd NEVER say
    common_typos: dict[str, str] = {}  # intentional quirks
    emoji_style: str  # heavy, moderate, minimal, none
    sentence_style: str  # short_punchy, long_playful, mix
    pet_names: List[str] = []
    content_boundaries: List[str] = []
    sample_winning_messages: List[str] = []
    voice_note_frequency: str = "occasional"  # frequent, occasional, rare
    response_length_target: int = 40  # target chars per message
```

**Step 3: Write failing test for loader**

```python
# tests/persona/test_loader.py
from src.persona.loader import PersonaLoader

def test_load_persona_from_yaml():
    loader = PersonaLoader(config_dir="config/creators")
    doc = loader.load("sunny_charm")
    assert doc.creator_id == "sunny_charm"
    assert len(doc.signature_phrases) >= 10
    assert len(doc.forbidden_phrases) >= 5

def test_load_nonexistent_creator_raises():
    loader = PersonaLoader(config_dir="config/creators")
    with pytest.raises(FileNotFoundError):
        loader.load("nonexistent_creator")
```

**Step 4: Implement loader**

```python
# src/persona/loader.py
import yaml
from pathlib import Path
from .models import PersonaDocument

class PersonaLoader:
    def __init__(self, config_dir: str = "config/creators"):
        self.config_dir = Path(config_dir)

    def load(self, creator_id: str) -> PersonaDocument:
        path = self.config_dir / f"{creator_id}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"No persona config for {creator_id}")
        with open(path) as f:
            data = yaml.safe_load(f)
        data["creator_id"] = creator_id
        return PersonaDocument(**data)
```

**Step 5: Write failing test for validator**

```python
# tests/persona/test_validator.py
from src.persona.models import PersonaDocument
from src.persona.validator import PersonaValidator

def test_validator_flags_forbidden_phrase():
    doc = PersonaDocument(
        creator_id="test",
        tone="flirty",
        signature_phrases=["hey"],
        forbidden_phrases=["daddy", "bro"],
        emoji_style="moderate",
        sentence_style="short_punchy",
    )
    validator = PersonaValidator(doc)
    result = validator.validate("hey daddy, how are you?")
    assert result.passed is False
    assert len(result.violations) >= 1
    assert "daddy" in str(result.violations)

def test_validator_passes_clean_message():
    doc = PersonaDocument(
        creator_id="test",
        tone="flirty",
        signature_phrases=["hey", "babe"],
        forbidden_phrases=["daddy"],
        emoji_style="moderate",
        sentence_style="short_punchy",
    )
    validator = PersonaValidator(doc)
    result = validator.validate("hey babe, how are you?")
    assert result.passed is True
    assert len(result.violations) == 0
```

**Step 6: Implement validator**

```python
# src/persona/validator.py
from dataclasses import dataclass, field
from .models import PersonaDocument

@dataclass
class ValidationResult:
    passed: bool
    violations: list[str] = field(default_factory=list)

class PersonaValidator:
    def __init__(self, persona: PersonaDocument):
        self.persona = persona

    def validate(self, message: str) -> ValidationResult:
        violations = []
        msg_lower = message.lower()
        for phrase in self.persona.forbidden_phrases:
            if phrase.lower() in msg_lower:
                violations.append(f"Forbidden phrase used: '{phrase}'")
        return ValidationResult(
            passed=len(violations) == 0,
            violations=violations,
        )
```

**Step 7: Create sample persona config**

```yaml
# config/creators/sunny_charm.yaml
tone: flirty
signature_phrases:
  - "hey babe"
  - "missed you"
  - "you're so sweet"
  - "I was just thinking about you"
  - "can't stop smiling"
  - "you make me feel so special"
  - "wish you were here"
  - "guess what I'm wearing"
  - "nobody else gets to see this"
  - "just for you"
forbidden_phrases:
  - "daddy"
  - "bro"
  - "what's up dude"
  - "yo"
  - "LOL"
common_typos:
  your: "ur"
  you: "u"
  are: "r"
emoji_style: moderate
sentence_style: short_punchy
pet_names:
  - babe
  - sweetie
  - handsome
content_boundaries:
  - "No meetups"
  - "No personal social media"
  - "No real name sharing"
sample_winning_messages: []
voice_note_frequency: occasional
response_length_target: 40
```

**Step 8: Run all tests**

```bash
pytest tests/persona/ -v
```
Expected: all pass

**Step 9: Commit**

```bash
git add src/persona/ tests/persona/ config/creators/
git commit -m "feat: persona system — loader + validator + sample config"
```

---

### Task 3: Five-Stage Funnel State Machine

**Objective:** Build a state machine that tracks every fan through the 5-stage funnel, enforces stage progression rules, and prevents skipping stages (e.g., never send PPV before Rapport).

**Files:**
- Create: `src/funnel/__init__.py`
- Create: `src/funnel/state_machine.py`
- Create: `src/funnel/session.py`
- Create: `tests/funnel/test_state_machine.py`
- Create: `tests/funnel/test_session.py`

**Step 1: Write failing test for FunnelStateMachine**

```python
# tests/funnel/test_state_machine.py
from src.funnel.state_machine import FunnelStateMachine, FunnelStage

def test_new_session_starts_at_rapport():
    sm = FunnelStateMachine()
    assert sm.current_stage == FunnelStage.RAPPORT

def test_cannot_skip_to_offer_from_rapport():
    sm = FunnelStateMachine()
    with pytest.raises(ValueError, match="Cannot transition"):
        sm.transition(FunnelStage.OFFER)

def test_valid_progression_rapport_to_tease():
    sm = FunnelStateMachine()
    sm.transition(FunnelStage.TEASE)
    assert sm.current_stage == FunnelStage.TEASE

def test_full_funnel_progression():
    sm = FunnelStateMachine()
    for stage in [FunnelStage.TEASE, FunnelStage.OFFER, FunnelStage.HANDLE, FunnelStage.CLOSE]:
        sm.transition(stage)
    assert sm.current_stage == FunnelStage.CLOSE

def test_cannot_move_backward():
    sm = FunnelStateMachine()
    sm.transition(FunnelStage.TEASE)
    sm.transition(FunnelStage.OFFER)
    with pytest.raises(ValueError):
        sm.transition(FunnelStage.TEASE)  # can't go back
```

**Step 2: Implement state machine**

```python
# src/funnel/state_machine.py
from enum import Enum

class FunnelStage(str, Enum):
    RAPPORT = "rapport"
    TEASE = "tease"
    OFFER = "offer"
    HANDLE = "handle"
    CLOSE = "close"

STAGE_ORDER = {
    FunnelStage.RAPPORT: 0,
    FunnelStage.TEASE: 1,
    FunnelStage.OFFER: 2,
    FunnelStage.HANDLE: 3,
    FunnelStage.CLOSE: 4,
}

ALLOWED_TRANSITIONS = {
    FunnelStage.RAPPORT: {FunnelStage.TEASE},
    FunnelStage.TEASE: {FunnelStage.OFFER, FunnelStage.RAPPORT},  # can fall back to rapport
    FunnelStage.OFFER: {FunnelStage.HANDLE, FunnelStage.TEASE},
    FunnelStage.HANDLE: {FunnelStage.CLOSE, FunnelStage.OFFER},
    FunnelStage.CLOSE: {FunnelStage.RAPPORT},  # restart funnel after close
}

class FunnelStateMachine:
    def __init__(self):
        self.current_stage = FunnelStage.RAPPORT
        self.stage_history: list[FunnelStage] = [FunnelStage.RAPPORT]
        self.messages_in_stage: int = 0

    def transition(self, to_stage: FunnelStage):
        if to_stage not in ALLOWED_TRANSITIONS.get(self.current_stage, set()):
            raise ValueError(
                f"Cannot transition from {self.current_stage.value} to {to_stage.value}"
            )
        self.current_stage = to_stage
        self.stage_history.append(to_stage)
        self.messages_in_stage = 0

    def can_send_ppv(self) -> bool:
        """PPV only allowed from OFFER stage onward."""
        return self.current_stage in {
            FunnelStage.OFFER,
            FunnelStage.HANDLE,
            FunnelStage.CLOSE,
        }

    def min_messages_before_tease(self) -> int:
        """Must have at least 2 rapport messages before teasing."""
        rapport_count = self.stage_history.count(FunnelStage.RAPPORT)
        return max(0, 2 - rapport_count)
```

**Step 3: Write failing test for FanSession**

```python
# tests/funnel/test_session.py
from src.funnel.session import FanSession
from src.funnel.state_machine import FunnelStage

def test_fan_session_tracks_messages():
    session = FanSession(fan_id="fan_001", creator_id="sunny_charm")
    session.add_message(sender="creator", content="Hey babe!")
    session.add_message(sender="subscriber", content="Hi!")
    assert session.message_count == 2
    assert session.funnel.current_stage == FunnelStage.RAPPORT

def test_fan_session_detects_ppv_block():
    session = FanSession(fan_id="fan_001", creator_id="sunny_charm")
    session.add_message(sender="creator", content="Hey!")
    # Only 1 message — can't tease yet
    assert session.funnel.min_messages_before_tease() > 0
```

**Step 4: Implement session**

```python
# src/funnel/session.py
from datetime import datetime
from .state_machine import FunnelStateMachine

class FanSession:
    def __init__(self, fan_id: str, creator_id: str):
        self.fan_id = fan_id
        self.creator_id = creator_id
        self.funnel = FunnelStateMachine()
        self.messages: list[dict] = []
        self.created_at = datetime.now()
        self.last_activity = datetime.now()

    def add_message(self, sender: str, content: str):
        self.messages.append({
            "sender": sender,
            "content": content,
            "timestamp": datetime.now(),
            "stage": self.funnel.current_stage,
        })
        self.last_activity = datetime.now()

    @property
    def message_count(self) -> int:
        return len(self.messages)
```

**Step 5: Run all tests + commit**

```bash
pytest tests/funnel/ -v && git add src/funnel/ tests/funnel/ && git commit -m "feat: 5-stage funnel state machine with PPV gating + fan session tracking"
```

---

### Task 4: Fan Notes Database

**Objective:** Persistent fan notes system — auto-extract preferences, purchase history, and emotional triggers from conversations. Load notes before every reply so fans feel remembered.

**Files:**
- Create: `src/notes/__init__.py`
- Create: `src/notes/models.py`
- Create: `src/notes/repository.py`
- Create: `src/notes/extractor.py`
- Create: `tests/notes/test_models.py`
- Create: `tests/notes/test_repository.py`
- Create: `tests/notes/test_extractor.py`

**Step 1: Write failing tests for FanNote model**

```python
# tests/notes/test_models.py
from src.notes.models import FanNote

def test_fan_note_required_fields():
    note = FanNote(
        fan_id="fan_001",
        creator_id="sunny_charm",
        display_name="Mike",
        preferences=["feet", "JOI"],
        occupation="truck driver",
        total_spent=245.50,
        purchase_count=7,
        last_purchase_at=None,
        emotional_triggers=["compliments", "being remembered"],
        hard_limits=["degradation"],
        notes="Loves golden retrievers. Works night shifts.",
    )
    assert note.fan_id == "fan_001"
    assert "feet" in note.preferences
    assert note.total_spent == 245.50

def test_fan_note_spend_tier():
    whale = FanNote(fan_id="w1", creator_id="c1", total_spent=600, purchase_count=15)
    assert whale.spend_tier == "whale"

    avg = FanNote(fan_id="a1", creator_id="c1", total_spent=80, purchase_count=3)
    assert avg.spend_tier == "average"

    tw = FanNote(fan_id="t1", creator_id="c1", total_spent=0, purchase_count=0)
    assert tw.spend_tier == "time_waster"
```

**Step 2: Implement FanNote model**

```python
# src/notes/models.py
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class FanNote(BaseModel):
    fan_id: str
    creator_id: str
    display_name: Optional[str] = None
    preferences: list[str] = []
    occupation: Optional[str] = None
    total_spent: float = 0.0
    purchase_count: int = 0
    last_purchase_at: Optional[datetime] = None
    emotional_triggers: list[str] = []
    hard_limits: list[str] = []
    notes: str = ""
    first_contact_at: Optional[datetime] = None
    relationship_stage: str = "new"  # new, warm, loyal, at_risk, lapsed

    @property
    def spend_tier(self) -> str:
        if self.total_spent >= 500:
            return "whale"
        if self.total_spent >= 50:
            return "average"
        return "time_waster"
```

**Step 3: Write failing test for repository (SQLite for now)**

```python
# tests/notes/test_repository.py
from src.notes.repository import FanNoteRepository
from src.notes.models import FanNote

def test_save_and_load_note():
    repo = FanNoteRepository(db_url="sqlite:///:memory:")
    repo.create_table()
    note = FanNote(fan_id="f1", creator_id="c1", display_name="Test")
    repo.save(note)
    loaded = repo.get("f1", "c1")
    assert loaded.display_name == "Test"

def test_update_note_merges_fields():
    repo = FanNoteRepository(db_url="sqlite:///:memory:")
    repo.create_table()
    note = FanNote(fan_id="f1", creator_id="c1", display_name="Old", total_spent=10)
    repo.save(note)
    note.display_name = "New"
    note.total_spent = 50
    repo.save(note)
    loaded = repo.get("f1", "c1")
    assert loaded.display_name == "New"
    assert loaded.total_spent == 50
```

**Step 4: Implement repository**

```python
# src/notes/repository.py
import json
from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, Text, MetaData, Table
from sqlalchemy.orm import sessionmaker
from .models import FanNote

class FanNoteRepository:
    def __init__(self, db_url: str):
        self.engine = create_engine(db_url)
        self.Session = sessionmaker(bind=self.engine)
        self.metadata = MetaData()
        self.table = Table(
            "fan_notes", self.metadata,
            Column("fan_id", String, primary_key=True),
            Column("creator_id", String, primary_key=True),
            Column("display_name", String, nullable=True),
            Column("preferences_json", Text, default="[]"),
            Column("occupation", String, nullable=True),
            Column("total_spent", Float, default=0),
            Column("purchase_count", Integer, default=0),
            Column("last_purchase_at", DateTime, nullable=True),
            Column("emotional_triggers_json", Text, default="[]"),
            Column("hard_limits_json", Text, default="[]"),
            Column("notes", Text, default=""),
            Column("relationship_stage", String, default="new"),
        )

    def create_table(self):
        self.metadata.create_all(self.engine)

    def save(self, note: FanNote):
        with self.Session() as session:
            row = {
                "fan_id": note.fan_id,
                "creator_id": note.creator_id,
                "display_name": note.display_name,
                "preferences_json": json.dumps(note.preferences),
                "occupation": note.occupation,
                "total_spent": note.total_spent,
                "purchase_count": note.purchase_count,
                "last_purchase_at": note.last_purchase_at,
                "emotional_triggers_json": json.dumps(note.emotional_triggers),
                "hard_limits_json": json.dumps(note.hard_limits),
                "notes": note.notes,
                "relationship_stage": note.relationship_stage,
            }
            session.execute(
                self.table.insert().values(**row).on_conflict_do_update(
                    index_elements=["fan_id", "creator_id"],
                    set_=row,
                )
            )
            session.commit()

    def get(self, fan_id: str, creator_id: str) -> FanNote | None:
        with self.Session() as session:
            row = session.execute(
                self.table.select().where(
                    (self.table.c.fan_id == fan_id) &
                    (self.table.c.creator_id == creator_id)
                )
            ).first()
            if not row:
                return None
            return FanNote(
                fan_id=row.fan_id,
                creator_id=row.creator_id,
                display_name=row.display_name,
                preferences=json.loads(row.preferences_json),
                occupation=row.occupation,
                total_spent=row.total_spent,
                purchase_count=row.purchase_count,
                last_purchase_at=row.last_purchase_at,
                emotional_triggers=json.loads(row.emotional_triggers_json),
                hard_limits=json.loads(row.hard_limits_json),
                notes=row.notes,
                relationship_stage=row.relationship_stage,
            )
```

**Step 5: Implement auto-extractor (LLM-based)**

```python
# src/notes/extractor.py
class NoteExtractor:
    """Extracts fan details from conversation using LLM."""

    EXTRACTION_PROMPT = """Extract fan details from this message. Return JSON:
{
  "display_name": "string or null",
  "preferences": ["kink1", "kink2"],
  "occupation": "string or null",
  "emotional_triggers": ["trigger1"],
  "hard_limits": ["limit1"],
  "notable_details": "anything worth remembering"
}
Message: {message}"""

    def __init__(self, llm_client):
        self.llm = llm_client

    async def extract(self, message: str) -> dict:
        prompt = self.EXTRACTION_PROMPT.format(message=message)
        response = await self.llm.complete(prompt)
        return json.loads(response)

    def merge(self, note: FanNote, extracted: dict) -> FanNote:
        if extracted.get("display_name") and not note.display_name:
            note.display_name = extracted["display_name"]
        for pref in extracted.get("preferences", []):
            if pref not in note.preferences:
                note.preferences.append(pref)
        if extracted.get("occupation") and not note.occupation:
            note.occupation = extracted["occupation"]
        for trigger in extracted.get("emotional_triggers", []):
            if trigger not in note.emotional_triggers:
                note.emotional_triggers.append(trigger)
        for limit in extracted.get("hard_limits", []):
            if limit not in note.hard_limits:
                note.hard_limits.append(limit)
        if extracted.get("notable_details"):
            note.notes += f"\n{extracted['notable_details']}"
        return note
```

**Step 6: Run tests + commit**

```bash
pytest tests/notes/ -v
git add src/notes/ tests/notes/
git commit -m "feat: fan notes — model, SQLite repository, LLM auto-extractor"
```

---

## PHASE 2: SCRIPT ENGINE

### Task 5: Multi-Script Framework Library

**Objective:** Build 17+ parameterized script templates covering welcome, PPV, re-engagement, objection handling, and custom negotiation. Each script is a template with `{variables}` that get filled per conversation.

**Files:**
- Create: `src/scripts/__init__.py`
- Create: `src/scripts/models.py`
- Create: `src/scripts/loader.py`
- Create: `src/scripts/engine.py`
- Create: `tests/scripts/test_models.py`
- Create: `tests/scripts/test_loader.py`
- Create: `tests/scripts/test_engine.py`

**Step 1: Write failing test for ScriptTemplate model**

```python
# tests/scripts/test_models.py
from src.scripts.models import ScriptTemplate, ScriptCategory, ScriptVariable

def test_script_template_has_required_fields():
    template = ScriptTemplate(
        name="welcome_noticed_you",
        category=ScriptCategory.WELCOME,
        description="Personalized welcome with question hook",
        messages=[
            "Hey {fan_name}! I noticed you just joined 💕",
            "What made you find me, {fan_name}?",
        ],
        variables=[
            ScriptVariable(name="fan_name", source="fan_notes.display_name", fallback="babe"),
        ],
    )
    assert template.category == ScriptCategory.WELCOME
    assert len(template.messages) == 2

def test_script_variable_fallback():
    var = ScriptVariable(name="fan_name", source="fan_notes.display_name", fallback="babe")
    assert var.resolve({"fan_notes": {}}) == "babe"
    assert var.resolve({"fan_notes": {"display_name": "Mike"}}) == "Mike"
```

**Step 2: Implement models**

```python
# src/scripts/models.py
from enum import Enum
from pydantic import BaseModel
from typing import Optional

class ScriptCategory(str, Enum):
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
    name: str
    source: str  # dot-path to value in context dict
    fallback: str = ""

    def resolve(self, context: dict) -> str:
        parts = self.source.split(".")
        value = context
        for part in parts:
            value = value.get(part, {}) if isinstance(value, dict) else None
        return str(value) if value else self.fallback

class ScriptTemplate(BaseModel):
    name: str
    category: ScriptCategory
    description: str
    messages: list[str]
    variables: list[ScriptVariable] = []
    conditions: dict = {}  # e.g., {"min_rapport_messages": 2}
```

**Step 3: Write the script library loader + test**

```python
# tests/scripts/test_loader.py
from src.scripts.loader import ScriptLibrary

def test_library_loads_all_categories():
    lib = ScriptLibrary()
    lib.load_builtin()
    categories = {s.category for s in lib.templates}
    assert ScriptCategory.WELCOME in categories
    assert ScriptCategory.PPV_SOFT_TEASE in categories
    assert ScriptCategory.OBJECTION_PRICE in categories
    assert len(lib.templates) >= 17  # All 17 script types

def test_get_scripts_by_category():
    lib = ScriptLibrary()
    lib.load_builtin()
    welcome_scripts = lib.get_by_category(ScriptCategory.WELCOME)
    assert len(welcome_scripts) >= 3  # Noticed You, Something Special, Question
```

**Step 4: Implement library + built-in templates (abbreviated — full 17 scripts)**

```python
# src/scripts/loader.py
from .models import ScriptTemplate, ScriptCategory, ScriptVariable

class ScriptLibrary:
    def __init__(self):
        self.templates: list[ScriptTemplate] = []

    def load_builtin(self):
        self.templates = BUILTIN_SCRIPTS  # See below

    def get_by_category(self, category: ScriptCategory) -> list[ScriptTemplate]:
        return [s for s in self.templates if s.category == category]

    def get(self, name: str) -> ScriptTemplate | None:
        for s in self.templates:
            if s.name == name:
                return s
        return None

BUILTIN_SCRIPTS = [
    # --- WELCOME SCRIPTS (3) ---
    ScriptTemplate(
        name="welcome_noticed_you",
        category=ScriptCategory.WELCOME,
        description="Personalized greeting with question hook",
        messages=[
            "Hey {fan_name}! I noticed you just joined 💕",
            "What made you find me, {fan_name}? I'd love to get to know you better",
        ],
        variables=[ScriptVariable(name="fan_name", source="fan_notes.display_name", fallback="babe")],
    ),
    ScriptTemplate(
        name="welcome_something_special",
        category=ScriptCategory.WELCOME,
        description="Teases exclusive content for new fans",
        messages=[
            "Welcome {fan_name}! I've got something special I made just for new fans like you...",
            "Want to see what I've been saving for the right person? 😏",
        ],
        variables=[ScriptVariable(name="fan_name", source="fan_notes.display_name", fallback="you")],
    ),
    ScriptTemplate(
        name="welcome_question",
        category=ScriptCategory.WELCOME,
        description="Asks preference to tailor first PPV",
        messages=[
            "Hey {fan_name}! So glad you found me 💕",
            "Quick question — what kind of content do you love most? I want to make sure you get exactly what you're into 😘",
        ],
        variables=[ScriptVariable(name="fan_name", source="fan_notes.display_name", fallback="there")],
    ),
    # --- PPV SCRIPTS (4) ---
    # ... (soft tease, direct, bundle, limited-time — each with 4-6 messages covering tease→offer→close)
    # --- RE-ENGAGEMENT SCRIPTS (4) ---
    # ... (3-day miss you, 7-day thinking of you, 14-day content tease, 30-day win-back)
    # --- OBJECTION SCRIPTS (4) ---
    # ... (price, free request, hesitation, already bought)
    # --- CUSTOM SCRIPTS (3) ---
    # ... (intake, upsell, delivery)
]
```

**Step 5: Implement script engine (variable resolution + conditions)**

```python
# src/scripts/engine.py
from .models import ScriptTemplate
from .loader import ScriptLibrary

class ScriptEngine:
    def __init__(self, library: ScriptLibrary):
        self.library = library

    def resolve(self, template: ScriptTemplate, context: dict) -> list[str]:
        """Fill template variables with context data."""
        resolved = []
        for msg in template.messages:
            for var in template.variables:
                value = var.resolve(context)
                msg = msg.replace(f"{{{var.name}}}", value)
            resolved.append(msg)
        return resolved

    def check_conditions(self, template: ScriptTemplate, context: dict) -> bool:
        """Verify conditions are met before running script."""
        conditions = template.conditions
        if "min_rapport_messages" in conditions:
            if context.get("rapport_count", 0) < conditions["min_rapport_messages"]:
                return False
        if "max_previous_purchases" in conditions:
            if context.get("purchase_count", 0) > conditions["max_previous_purchases"]:
                return False
        if "min_total_spent" in conditions:
            if context.get("total_spent", 0) < conditions["min_total_spent"]:
                return False
        return True

    def get_script_for_stage(self, stage: str, context: dict) -> ScriptTemplate | None:
        """Select the best script for the current funnel stage and context."""
        candidates = self.library.templates
        # Filter by stage-appropriate categories
        # Filter by conditions
        # Return best match
        for template in candidates:
            if self.check_conditions(template, context):
                return template
        return None
```

**Step 6: Run tests + commit**

```bash
pytest tests/scripts/ -v
git add src/scripts/ tests/scripts/
git commit -m "feat: 17-script template library with variable resolution + condition engine"
```

---

### Task 6: Fan Type Auto-Detection

**Objective:** Classify each fan into one of 5 personality types from their first 2-3 messages. Routes them to the right script variant and NLP approach.

**Files:**
- Create: `src/profiling/__init__.py`
- Create: `src/profiling/classifier.py`
- Create: `tests/profiling/test_classifier.py`

**Step 1: Write failing test**

```python
# tests/profiling/test_classifier.py
from src.profiling.classifier import FanClassifier

def test_classify_instant_buyer():
    classifier = FanClassifier()
    messages = ["Hey! Love your content 😍 What PPVs do you have?"]
    result = classifier.classify(messages)
    assert result.personality_type == "instant_buyer"

def test_classify_quiet_lurker():
    classifier = FanClassifier()
    messages = ["hi"]  # Minimal, short
    result = classifier.classify(messages)
    assert result.personality_type == "quiet_lurker"

def test_classify_chatty_fan():
    classifier = FanClassifier()
    messages = [
        "Hey! How are you? I've been following you on Instagram forever!",
        "Your content is amazing, seriously. What do you do for fun outside this?",
    ]
    result = classifier.classify(messages)
    assert result.personality_type == "chatty_fan"

def test_classifier_returns_confidence():
    classifier = FanClassifier()
    messages = ["Hey! Love your stuff, what content do you have?"]
    result = classifier.classify(messages)
    assert 0 <= result.confidence <= 1.0
```

**Step 2: Implement keyword + heuristic classifier**

```python
# src/profiling/classifier.py
from dataclasses import dataclass

@dataclass
class ClassificationResult:
    personality_type: str
    confidence: float
    evidence: list[str]

class FanClassifier:
    PATTERNS = {
        "instant_buyer": {
            "keywords": ["PPV", "buy", "content", "video", "unlock", "price", "how much", "purchase"],
            "indicators": ["asks about content immediately", "mentions buying", "skips small talk"],
        },
        "quiet_lurker": {
            "keywords": [],
            "indicators": ["very short messages", "one-word replies", "low engagement"],
        },
        "attention_seeker": {
            "keywords": ["notice me", "reply", "please", "hello??", "anyone there", "talk to me"],
            "indicators": ["demands attention", "double-texts quickly", "validation-seeking language"],
        },
        "tester": {
            "keywords": ["free", "discount", "why so much", "really?", "prove it", "sample"],
            "indicators": ["questions pricing", "asks for free content", "skeptical tone"],
        },
        "chatty_fan": {
            "keywords": [],
            "indicators": ["long messages", "asks personal questions", "shares about themselves", "high engagement"],
        },
    }

    def classify(self, messages: list[str]) -> ClassificationResult:
        combined = " ".join(messages).lower()
        scores = {}
        evidence = []

        for ptype, patterns in self.PATTERNS.items():
            score = 0
            for kw in patterns["keywords"]:
                if kw.lower() in combined:
                    score += 1
            scores[ptype] = score

        # Heuristic adjustments
        avg_len = sum(len(m) for m in messages) / max(len(messages), 1)

        if avg_len < 10:
            scores["quiet_lurker"] += 2
            evidence.append("very short messages")
        if avg_len > 80:
            scores["chatty_fan"] += 2
            evidence.append("long detailed messages")
        if len(messages) > 2:
            scores["chatty_fan"] += 1
            scores["attention_seeker"] += 0.5

        # Pick winner
        best_type = max(scores, key=scores.get)
        max_score = scores[best_type]
        total = sum(scores.values()) or 1
        confidence = max_score / total if total > 0 else 0.2

        return ClassificationResult(
            personality_type=best_type,
            confidence=min(confidence, 1.0),
            evidence=evidence,
        )
```

**Step 3: Run tests + commit**

```bash
pytest tests/profiling/ -v
git add src/profiling/ tests/profiling/
git commit -m "feat: fan personality classifier — 5 types from first messages"
```

---

### Task 7: Push-Pull Rhythm Engine

**Objective:** Alternate between normal conversation (pull) and flirtatious spikes (push). After a push, step back and let the fan steer back to sexual territory before offering content.

**Files:**
- Create: `src/rhythm/__init__.py`
- Create: `src/rhythm/engine.py`
- Create: `tests/rhythm/test_engine.py`

**Step 1: Write failing test**

```python
# tests/rhythm/test_engine.py
from src.rhythm.engine import PushPullEngine, RhythmPhase

def test_starts_in_pull_phase():
    engine = PushPullEngine()
    assert engine.current_phase == RhythmPhase.PULL

def test_alternates_push_pull():
    engine = PushPullEngine()
    engine.next()  # PULL → PUSH
    assert engine.current_phase == RhythmPhase.PUSH
    engine.next()  # PUSH → PULL
    assert engine.current_phase == RhythmPhase.PULL

def test_cannot_push_twice_in_a_row():
    engine = PushPullEngine()
    engine.next()  # now PUSH
    with pytest.raises(ValueError, match="Cannot push"):
        engine.force_push()

def test_detect_fan_initiated_return():
    engine = PushPullEngine()
    engine.next()  # PUSH
    # Fan steers back to sexual topic — good signal
    result = engine.analyze_fan_message("So... what are you wearing right now?")
    assert result.fan_initiated is True
    assert result.ready_for_tease is True

def test_fan_ignores_push_stays_in_push():
    engine = PushPullEngine()
    engine.next()  # PUSH
    result = engine.analyze_fan_message("Anyway, how was your day?")
    assert result.fan_initiated is False
    assert result.ready_for_tease is False
```

**Step 2: Implement engine**

```python
# src/rhythm/engine.py
from enum import Enum
from dataclasses import dataclass

class RhythmPhase(str, Enum):
    PULL = "pull"  # Normal conversation, building rapport
    PUSH = "push"  # Flirtatious spike, then step back

PUSH_INDICATORS = [
    "what are you wearing", "send me", "show me", "can i see",
    "you're so hot", "i want to see", "what would you do",
    "tell me more", "i'm so turned on", "you make me",
]

@dataclass
class FanMessageAnalysis:
    fan_initiated: bool
    ready_for_tease: bool
    detected_indicators: list[str]

class PushPullEngine:
    def __init__(self):
        self.phase_history: list[RhythmPhase] = [RhythmPhase.PULL]
        self.push_count: int = 0
        self.pull_count: int = 0

    @property
    def current_phase(self) -> RhythmPhase:
        return self.phase_history[-1]

    def next(self):
        """Toggle to the next phase."""
        if self.current_phase == RhythmPhase.PULL:
            self.phase_history.append(RhythmPhase.PUSH)
            self.push_count += 1
        else:
            self.phase_history.append(RhythmPhase.PULL)
            self.pull_count += 1

    def force_push(self):
        if self.current_phase == RhythmPhase.PUSH:
            raise ValueError("Cannot push twice in a row — must pull first")
        self.next()

    def analyze_fan_message(self, message: str) -> FanMessageAnalysis:
        msg_lower = message.lower()
        indicators = [ind for ind in PUSH_INDICATORS if ind in msg_lower]
        fan_initiated = len(indicators) > 0
        ready = fan_initiated and self.current_phase == RhythmPhase.PUSH
        return FanMessageAnalysis(
            fan_initiated=fan_initiated,
            ready_for_tease=ready,
            detected_indicators=indicators,
        )
```

**Step 3: Run tests + commit**

```bash
pytest tests/rhythm/ -v
git add src/rhythm/ tests/rhythm/
git commit -m "feat: push-pull rhythm engine with fan initiation detection"
```

---

## PHASE 3-6 TASKS (abbreviated — same TDD pattern applies)

### Task 8: "Wait For Me" Delay System
- `src/timing/delays.py` — configurable delays between upsell steps
- Tests verify delays fire between ladder steps, don't exceed stated time

### Task 9: Aftercare Sequence Engine
- `src/aftercare/engine.py` — triggers post-purchase selfie + voice note
- Fan tagged `aftercare_delivered` — refund risk cut 3x

### Task 10: Mass Messaging with Segmentation
- `src/mass_messaging/engine.py` — segment fans, attach GIFs, rate limit
- Tests verify per-segment opener variation, GIF attachment

### Task 11: NLP Trigger System
- `src/nlp/triggers.py` — thought-of-you, embedded commands, anchoring
- Tests verify trigger detection from fan notes, command insertion

### Task 12: Reciprocity Engine
- `src/reciprocity/engine.py` — track free sends → debt → premium PPV
- Tests verify debt tracking, premium PPV trigger after free send

### Task 13: Objection Handling Dispatcher
- `src/objections/dispatcher.py` — classify objection type → load handler → resolve → resume
- Tests verify pause/resume pattern, 4 objection types

### Task 14: Three-Tier Auto-Classification
- `src/tiers/classifier.py` — time_waster / average / whale based on spend
- Tests verify threshold logic, auto-promotion/demotion

### Task 15: Whale Nurture Pipeline
- `src/whales/pipeline.py` — detect signals → nurture → VIP treatment
- Tests verify early signal detection, VIP routing

### Task 16: Churn Prediction
- `src/churn/predictor.py` — days since purchase + sentiment → risk score
- Tests verify risk scoring, auto-trigger re-engagement

### Task 17: KPI Dashboard + A/B Testing
- `src/analytics/dashboard.py` — all metrics tracked
- `src/analytics/ab_testing.py` — variant assignment, measurement, promotion
- Tests verify metric calculation, split testing logic

---

## VERIFICATION CHECKLIST (after all tasks)

- [ ] All 200+ tests pass: `pytest tests/ -v -q`
- [ ] Persona validator blocks forbidden phrases
- [ ] Funnel state machine prevents PPV before rapport
- [ ] Fan notes persist and auto-extract from conversation
- [ ] 17 script templates load and resolve variables
- [ ] Fan classifier correctly identifies all 5 types
- [ ] Push-pull alternates and detects fan initiation
- [ ] Delay system inserts realistic pauses
- [ ] Aftercare triggers after purchase
- [ ] Mass messages segment and attach GIFs
- [ ] Reciprocity tracks debt and triggers premium offers
- [ ] Objection dispatcher pauses and resumes correctly
- [ ] Tier classification updates on spend changes
- [ ] Whale pipeline detects early signals
- [ ] Churn prediction fires re-engagement at right time
- [ ] KPI dashboard computes all metrics
- [ ] A/B testing splits traffic and measures outcomes

## FINAL COMMIT

```bash
git add -A
git commit -m "feat: complete 17-system Fansly AI chatbot implementation"
```