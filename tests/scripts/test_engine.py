"""Tests for ScriptEngine — RED phase (tests written before implementation)."""

import pytest
from src.scripts.engine import ScriptEngine
from src.scripts.loader import ScriptLibrary
from src.scripts.models import ScriptTemplate, ScriptCategory, ScriptVariable


class TestScriptEngine:
    """ScriptEngine: resolve, conditions, stage matching."""

    @pytest.fixture
    def library(self):
        """Return a freshly loaded ScriptLibrary."""
        lib = ScriptLibrary()
        lib.load_builtin()
        return lib

    @pytest.fixture
    def engine(self, library):
        return ScriptEngine(library)

    # ── resolve tests ──────────────────────────────────────────

    def test_resolve_fills_variables(self, engine):
        """Template with {fan_name}, context has display_name "Mike" → "Hey Mike!\""""
        template = ScriptTemplate(
            name="test_welcome",
            category=ScriptCategory.WELCOME,
            description="Test",
            messages=["Hey {fan_name}! Welcome 💕"],
            variables=[
                ScriptVariable(
                    name="fan_name",
                    source="fan_notes.display_name",
                    fallback="friend",
                ),
            ],
        )
        context = {"fan_notes": {"display_name": "Mike"}}
        results = engine.resolve(template, context)
        assert results == ["Hey Mike! Welcome 💕"]

    def test_resolve_multiple_variables(self, engine):
        """Template with multiple variables, all filled from context."""
        template = ScriptTemplate(
            name="test_offer",
            category=ScriptCategory.PPV_DIRECT,
            description="Test offer",
            messages=[
                "Hey {fan_name}! Check out my {content_detail} for just ${price} 🔥",
            ],
            variables=[
                ScriptVariable(name="fan_name", source="fan_notes.display_name", fallback="friend"),
                ScriptVariable(name="content_detail", source="offer.description", fallback="exclusive content"),
                ScriptVariable(name="price", source="offer.price", fallback="9.99"),
            ],
        )
        context = {
            "fan_notes": {"display_name": "Jake"},
            "offer": {"description": "naughty photoset", "price": "14.99"},
        }
        results = engine.resolve(template, context)
        assert results == ["Hey Jake! Check out my naughty photoset for just $14.99 🔥"]

    def test_resolve_missing_variable_uses_fallback(self, engine):
        """When context is missing a variable, fallback is used."""
        template = ScriptTemplate(
            name="test_fallback",
            category=ScriptCategory.WELCOME,
            description="Test fallback",
            messages=["Hey {fan_name}!"],
            variables=[
                ScriptVariable(name="fan_name", source="fan_notes.display_name", fallback="friend"),
            ],
        )
        results = engine.resolve(template, {})
        assert results == ["Hey friend!"]

    def test_resolve_multiple_messages(self, engine):
        """Template with multiple messages, all resolved."""
        template = ScriptTemplate(
            name="test_multi",
            category=ScriptCategory.PPV_SOFT_TEASE,
            description="Test multi messages",
            messages=[
                "Hey {fan_name}!",
                "I have some {content} for you 😉",
            ],
            variables=[
                ScriptVariable(name="fan_name", source="fan_notes.display_name", fallback="friend"),
                ScriptVariable(name="content", source="offer.detail", fallback="special content"),
            ],
        )
        context = {"fan_notes": {"display_name": "Sam"}, "offer": {"detail": "behind-the-scenes pics"}}
        results = engine.resolve(template, context)
        assert len(results) == 2
        assert results[0] == "Hey Sam!"
        assert results[1] == "I have some behind-the-scenes pics for you 😉"

    # ── conditions tests ───────────────────────────────────────

    def test_conditions_pass_when_met(self, engine):
        """min_rapport_messages condition passes when context meets threshold."""
        template = ScriptTemplate(
            name="test_conditioned",
            category=ScriptCategory.REENGAGE_3DAY,
            description="Test condition",
            messages=["Yo!"],
            conditions={"min_rapport_messages": 2},
        )
        context = {"rapport_messages": 5}
        assert engine.check_conditions(template, context) is True

    def test_conditions_fail_when_not_met(self, engine):
        """min_rapport_messages condition fails when context is below threshold."""
        template = ScriptTemplate(
            name="test_conditioned",
            category=ScriptCategory.REENGAGE_3DAY,
            description="Test condition",
            messages=["Yo!"],
            conditions={"min_rapport_messages": 2},
        )
        context = {"rapport_messages": 0}
        assert engine.check_conditions(template, context) is False

    def test_conditions_no_conditions_passes(self, engine):
        """Template with empty conditions dict always passes."""
        template = ScriptTemplate(
            name="no_conditions",
            category=ScriptCategory.WELCOME,
            description="No conditions",
            messages=["Hello!"],
        )
        assert engine.check_conditions(template, {}) is True

    def test_conditions_max_previous_purchases(self, engine):
        """max_previous_purchases condition: pass when below max."""
        template = ScriptTemplate(
            name="newbie_offer",
            category=ScriptCategory.PPV_SOFT_TEASE,
            description="First-timer offer",
            messages=["Special first time offer!"],
            conditions={"max_previous_purchases": 3},
        )
        context = {"previous_purchases": 1}
        assert engine.check_conditions(template, context) is True

    def test_conditions_max_previous_purchases_exceeded(self, engine):
        """max_previous_purchases condition: fail when exceeded."""
        template = ScriptTemplate(
            name="newbie_offer",
            category=ScriptCategory.PPV_SOFT_TEASE,
            description="First-timer offer",
            messages=["Special first time offer!"],
            conditions={"max_previous_purchases": 3},
        )
        context = {"previous_purchases": 5}
        assert engine.check_conditions(template, context) is False

    def test_conditions_min_total_spent(self, engine):
        """min_total_spent condition: pass when above threshold."""
        template = ScriptTemplate(
            name="vip_offer",
            category=ScriptCategory.PPV_BUNDLE,
            description="VIP bundle",
            messages=["VIP deal for you!"],
            conditions={"min_total_spent": 50.0},
        )
        context = {"total_spent": 100.0}
        assert engine.check_conditions(template, context) is True

    def test_conditions_min_total_spent_not_met(self, engine):
        """min_total_spent condition: fail when below threshold."""
        template = ScriptTemplate(
            name="vip_offer",
            category=ScriptCategory.PPV_BUNDLE,
            description="VIP bundle",
            messages=["VIP deal for you!"],
            conditions={"min_total_spent": 50.0},
        )
        context = {"total_spent": 10.0}
        assert engine.check_conditions(template, context) is False

    def test_conditions_multiple_all_must_pass(self, engine):
        """Multiple conditions: ALL must pass (AND logic)."""
        template = ScriptTemplate(
            name="qualified_offer",
            category=ScriptCategory.PPV_DIRECT,
            description="Qualified only",
            messages=["You qualify!"],
            conditions={
                "min_rapport_messages": 2,
                "min_total_spent": 25.0,
                "max_previous_purchases": 10,
            },
        )
        context = {"rapport_messages": 4, "total_spent": 100.0, "previous_purchases": 5}
        assert engine.check_conditions(template, context) is True

    def test_conditions_multiple_one_fails(self, engine):
        """Multiple conditions: if ONE fails, result is False."""
        template = ScriptTemplate(
            name="qualified_offer",
            category=ScriptCategory.PPV_DIRECT,
            description="Qualified only",
            messages=["You qualify!"],
            conditions={
                "min_rapport_messages": 2,
                "min_total_spent": 25.0,
                "max_previous_purchases": 10,
            },
        )
        context = {"rapport_messages": 4, "total_spent": 100.0, "previous_purchases": 15}
        assert engine.check_conditions(template, context) is False

    # ── get_script_for_stage tests ──────────────────────────────

    def test_get_script_matches_stage_welcome(self, engine):
        """get_script_for_stage with 'welcome' should return a WELCOME template."""
        context = {"rapport_messages": 5, "total_spent": 50.0, "previous_purchases": 0}
        script = engine.get_script_for_stage("welcome", context)
        assert script is not None
        assert script.category == ScriptCategory.WELCOME

    def test_get_script_matches_stage_unknown_returns_none(self, engine):
        """get_script_for_stage with unknown stage returns None."""
        script = engine.get_script_for_stage("nonexistent_stage", {})
        assert script is None