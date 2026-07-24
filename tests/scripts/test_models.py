"""Tests for script models — RED phase (tests written before implementation)."""

import pytest
from src.scripts.models import ScriptTemplate, ScriptCategory, ScriptVariable


class TestScriptVariable:
    """ScriptVariable: resolve with context and fallback."""

    def test_resolve_with_context(self):
        """Walk dot-path through context dict and return the value."""
        var = ScriptVariable(
            name="fan_name",
            source="fan_notes.display_name",
            fallback="friend",
        )
        context = {
            "fan_notes": {
                "display_name": "Mike",
            },
        }
        assert var.resolve(context) == "Mike"

    def test_fallback_when_missing(self):
        """Return fallback when dot-path key is missing."""
        var = ScriptVariable(
            name="fan_name",
            source="fan_notes.display_name",
            fallback="friend",
        )
        context = {}
        assert var.resolve(context) == "friend"

    def test_fallback_when_partial_path(self):
        """Return fallback when intermediate path segments are missing."""
        var = ScriptVariable(
            name="content",
            source="fan.preferences.type",
            fallback="exclusive content",
        )
        context = {"fan": None}
        assert var.resolve(context) == "exclusive content"

    def test_deeply_nested_path(self):
        """Resolve a deeply nested dot-path."""
        var = ScriptVariable(
            name="trigger",
            source="data.profile.emotion.triggers.primary",
            fallback="curiosity",
        )
        context = {
            "data": {
                "profile": {
                    "emotion": {
                        "triggers": {"primary": "exclusivity"},
                    },
                },
            },
        }
        assert var.resolve(context) == "exclusivity"


class TestScriptTemplate:
    """ScriptTemplate: required fields, defaults, category enum."""

    def test_required_fields(self):
        """Create a minimal ScriptTemplate and verify fields."""
        template = ScriptTemplate(
            name="welcome_basic",
            category=ScriptCategory.WELCOME,
            description="Basic welcome message",
            messages=["Hey {fan_name}! Welcome to my page 💕"],
        )
        assert template.name == "welcome_basic"
        assert template.category == ScriptCategory.WELCOME
        assert template.description == "Basic welcome message"
        assert len(template.messages) == 1
        assert template.variables == []
        assert template.conditions == {}

    def test_with_variables(self):
        """ScriptTemplate with defined variables."""
        template = ScriptTemplate(
            name="welcome_personalized",
            category=ScriptCategory.WELCOME,
            description="Personalized welcome with fan name",
            messages=["Hey {fan_name}! Welcome to my page 💕"],
            variables=[
                ScriptVariable(
                    name="fan_name",
                    source="fan_notes.display_name",
                    fallback="friend",
                ),
            ],
        )
        assert len(template.variables) == 1
        assert template.variables[0].name == "fan_name"

    def test_with_conditions(self):
        """ScriptTemplate with conditions dict."""
        template = ScriptTemplate(
            name="reengage_loyal",
            category=ScriptCategory.REENGAGE_7DAY,
            description="Re-engage fans after 7 days",
            messages=["Miss you {fan_name}! 😘"],
            conditions={"min_rapport_messages": 2, "max_previous_purchases": 5},
        )
        assert template.conditions["min_rapport_messages"] == 2
        assert template.conditions["max_previous_purchases"] == 5

    def test_category_enum_values(self):
        """Verify all expected ScriptCategory values exist."""
        categories = [
            ScriptCategory.WELCOME,
            ScriptCategory.PPV_SOFT_TEASE,
            ScriptCategory.PPV_DIRECT,
            ScriptCategory.PPV_BUNDLE,
            ScriptCategory.PPV_LIMITED_TIME,
            ScriptCategory.REENGAGE_3DAY,
            ScriptCategory.REENGAGE_7DAY,
            ScriptCategory.REENGAGE_14DAY,
            ScriptCategory.REENGAGE_30DAY,
            ScriptCategory.OBJECTION_PRICE,
            ScriptCategory.OBJECTION_FREE,
            ScriptCategory.OBJECTION_HESITATE,
            ScriptCategory.OBJECTION_ALREADY_BOUGHT,
            ScriptCategory.CUSTOM_INTAKE,
            ScriptCategory.CUSTOM_UPSELL,
            ScriptCategory.CUSTOM_DELIVERY,
        ]
        assert len(categories) == 16