"""Tests for ScriptLibrary loader — RED phase (tests written before implementation)."""

import pytest
from src.scripts.loader import ScriptLibrary
from src.scripts.models import ScriptCategory, ScriptTemplate


class TestScriptLibrary:
    """ScriptLibrary: load builtin, get by category/name."""

    @pytest.fixture
    def library(self):
        """Return a freshly loaded ScriptLibrary."""
        lib = ScriptLibrary()
        lib.load_builtin()
        return lib

    def test_library_loads_builtin(self, library):
        """load_builtin should populate at least 17 templates."""
        assert len(library.templates) >= 17

    def test_get_by_category_returns_correct_scripts(self, library):
        """get_by_category should filter templates by category."""
        welcome_scripts = library.get_by_category(ScriptCategory.WELCOME)
        assert len(welcome_scripts) >= 3
        for script in welcome_scripts:
            assert script.category == ScriptCategory.WELCOME

    def test_get_by_category_ppv(self, library):
        """PPV-related categories should return templates."""
        ppv_cats = [
            ScriptCategory.PPV_SOFT_TEASE,
            ScriptCategory.PPV_DIRECT,
            ScriptCategory.PPV_BUNDLE,
            ScriptCategory.PPV_LIMITED_TIME,
        ]
        for cat in ppv_cats:
            scripts = library.get_by_category(cat)
            assert len(scripts) >= 1, f"No scripts for {cat}"

    def test_get_by_name_returns_correct_template(self, library):
        """get should return the template with matching name."""
        template = library.get("welcome_basic")
        assert template is not None
        assert template.name == "welcome_basic"
        assert template.category == ScriptCategory.WELCOME

    def test_get_by_name_not_found(self, library):
        """get should return None for unknown template name."""
        template = library.get("nonexistent_script")
        assert template is None

    def test_get_by_category_empty(self, library):
        """get_by_category with unused category should return empty list."""
        # All categories should have at least something now, but test the method
        # Create a fresh empty library to test empty case
        empty_lib = ScriptLibrary()
        assert empty_lib.get_by_category(ScriptCategory.WELCOME) == []

    def test_all_categories_have_templates(self, library):
        """Every ScriptCategory value should have at least one template."""
        for cat in ScriptCategory:
            scripts = library.get_by_category(cat)
            assert len(scripts) >= 1, f"Category {cat} has no templates"

    def test_each_template_has_required_metadata(self, library):
        """Every builtin template should have name, description, and at least one message."""
        for template in library.templates:
            assert template.name, f"Template missing name"
            assert template.description, f"Template {template.name} missing description"
            assert len(template.messages) > 0, f"Template {template.name} has no messages"