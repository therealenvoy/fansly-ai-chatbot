"""Tests for the Whale Pipeline."""

import pytest

from src.whales.pipeline import WhalePipeline


class TestWhalePipeline:
    """Tests for the WhalePipeline class."""

    # ── 1. detect job mention signal ──────────────────────────────────
    def test_detect_job_signal(self):
        """detect_signals should find job_mention when messages reference work/money."""
        pipeline = WhalePipeline()
        signals = pipeline.detect_signals(
            messages=["hey babe", "just got done with my shift as a software engineer"],
            fan_notes={},
        )
        assert "job_mention" in signals

    # ── 2. detect big tip signal ─────────────────────────────────────
    def test_detect_big_tip_signal(self):
        """detect_signals should find big_tip when fan_notes indicate large tips."""
        pipeline = WhalePipeline()
        signals = pipeline.detect_signals(
            messages=["thanks for the content"],
            fan_notes={"total_tips": 200, "max_single_tip": 100},
        )
        assert "big_tip" in signals

    # ── 3. potential whale needs 2+ signals ──────────────────────────
    def test_potential_whale_needs_2_signals(self):
        """is_potential_whale should return True with 2 signals."""
        pipeline = WhalePipeline()
        assert pipeline.is_potential_whale(["job_mention", "big_tip"]) is True
        assert pipeline.is_potential_whale(
            ["job_mention", "rapid_purchasing", "custom_request"]
        ) is True

    # ── 4. not a whale with only 1 signal ────────────────────────────
    def test_not_whale_with_1_signal(self):
        """is_potential_whale should return False with fewer than 2 signals."""
        pipeline = WhalePipeline()
        assert pipeline.is_potential_whale([]) is False
        assert pipeline.is_potential_whale(["job_mention"]) is False
        assert pipeline.is_potential_whale(["big_tip"]) is False

    # ── 5. nurture phase timeline ────────────────────────────────────
    def test_nurture_phase_timeline(self):
        """nurture_phase should return the correct phase for each day range."""
        pipeline = WhalePipeline()
        assert pipeline.nurture_phase("fan1", 0) == "rapport"
        assert pipeline.nurture_phase("fan1", 7) == "rapport"
        assert pipeline.nurture_phase("fan1", 14) == "reciprocity"
        assert pipeline.nurture_phase("fan1", 20) == "reciprocity"
        assert pipeline.nurture_phase("fan1", 30) == "targeted_asks"
        assert pipeline.nurture_phase("fan1", 45) == "targeted_asks"
        assert pipeline.nurture_phase("fan1", 60) == "vip"
        assert pipeline.nurture_phase("fan1", 100) == "vip"

    # ── 6. vip treatment has required keys ───────────────────────────
    def test_vip_treatment_keys(self):
        """vip_treatment should return the expected dict with all VIP flags."""
        pipeline = WhalePipeline()
        treatment = pipeline.vip_treatment("fan42")
        assert treatment == {
            "priority_response": True,
            "exclusive_content": True,
            "premium_pricing": True,
            "dedicated_chatter": True,
        }
