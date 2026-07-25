"""Tests for VariationPool — eliminates repetition in bot responses.

TDD: Write test first (RED), watch it fail, implement minimal code (GREEN).
"""

import pytest
from src.humanize.variation import VariationPool, RAPPORT_VARIANTS, PUSH_VARIANTS


@pytest.fixture
def pool():
    return VariationPool()


# ─── BASIC POOL BEHAVIOR ────────────────────────────────

class TestPoolBasics:
    def test_pick_returns_string(self, pool):
        result = pool.pick("rapport")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_pick_returns_different_values(self, pool):
        """Two consecutive picks should not return the same variant."""
        a = pool.pick("rapport")
        b = pool.pick("rapport")
        assert a != b

    def test_pick_unknown_key_returns_fallback(self, pool):
        result = pool.pick("nonexistent_key")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_pick_cycles_through_all_variants(self, pool):
        """After enough picks, we should see all variants."""
        seen = set()
        for _ in range(20):
            seen.add(pool.pick("rapport"))
        # We should have seen at least 5 unique variants (pool has 8)
        assert len(seen) >= 5

    def test_pick_with_context_fan_aware(self, pool):
        """Different fans should get different variants for the same key."""
        fan_a = pool.pick_with_context("rapport", "fan_1")
        fan_b = pool.pick_with_context("rapport", "fan_2")
        # At minimum, should both be valid strings
        assert isinstance(fan_a, str) and isinstance(fan_b, str)

    def test_pick_with_context_same_fan_no_repeat(self, pool):
        """Same fan should not get the same variant twice in a row."""
        a = pool.pick_with_context("push", "fan_42")
        b = pool.pick_with_context("push", "fan_42")
        assert a != b


# ─── POOL EXHAUSTION ────────────────────────────────────

class TestPoolExhaustion:
    def test_pool_resets_after_exhaustion(self, pool):
        """After cycling through all variants, pool resets without error."""
        key = "rapport"
        for _ in range(50):
            result = pool.pick(key)
            assert isinstance(result, str) and len(result) > 0


# ─── VARIANT QUALITY ────────────────────────────────────

class TestVariantQuality:
    def test_rapport_variants_are_unique(self):
        """All rapport variants should be distinct strings."""
        assert len(set(RAPPORT_VARIANTS)) == len(RAPPORT_VARIANTS)

    def test_push_variants_are_unique(self):
        assert len(set(PUSH_VARIANTS)) == len(PUSH_VARIANTS)

    def test_rapport_variants_no_ai_tells(self):
        """Rapport variants should not contain common AI vocabulary."""
        ai_words = ["delve", "showcase", "underscore", "pivotal", "tapestry"]
        for v in RAPPORT_VARIANTS:
            for word in ai_words:
                assert word not in v.lower()

    def test_push_variants_have_personality(self):
        """Push variants should feel human, not templated."""
        for v in PUSH_VARIANTS:
            # Should not be empty or very short
            assert len(v) > 15