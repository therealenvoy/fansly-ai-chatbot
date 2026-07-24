"""Tests for the Mass Messaging Engine."""

from datetime import datetime, timedelta, timezone

import pytest

from src.mass_messaging.engine import Campaign, MassMessagingEngine


class TestCampaignFields:
    """Tests for the Campaign dataclass fields."""

    def test_campaign_has_required_fields(self):
        """Campaign should expose content_id, segments, segment_openers, preview_url, and metadata."""
        campaign = Campaign(
            campaign_id="camp_001",
            content_id="content_42",
            creator_id="creator_1",
            segments=["instant_buyer", "quiet_lurker"],
            segment_openers={
                "instant_buyer": "Hey bestie! Check this out 🔥",
                "quiet_lurker": "Psst... got something special for you 👀",
            },
            preview_url="https://example.com/preview/42",
            status="sent",
            sent_at=datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        )

        assert campaign.campaign_id == "camp_001"
        assert campaign.content_id == "content_42"
        assert campaign.creator_id == "creator_1"
        assert campaign.segments == ["instant_buyer", "quiet_lurker"]
        assert campaign.segment_openers == {
            "instant_buyer": "Hey bestie! Check this out 🔥",
            "quiet_lurker": "Psst... got something special for you 👀",
        }
        assert campaign.preview_url == "https://example.com/preview/42"
        assert campaign.status == "sent"
        assert campaign.sent_at == datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

    def test_campaign_defaults(self):
        """Campaign should generate a campaign_id and use sensible defaults when not provided."""
        campaign = Campaign(
            content_id="content_99",
            creator_id="creator_x",
            segments=[],
            segment_openers={},
            preview_url="https://example.com/preview/99",
        )

        assert campaign.campaign_id  # auto-generated, non-empty
        assert campaign.status == "draft"
        assert campaign.sent_at is not None


class TestBuildSegmentOpeners:
    """Tests for build_segment_openers method."""

    def test_segment_openers_differ(self):
        """Each segment should get a different personalized opener."""
        engine = MassMessagingEngine(creator_id="creator_1")
        base_message = "Check out my new content! 🔥"
        segments = ["instant_buyer", "quiet_lurker", "attention_seeker"]

        openers = engine.build_segment_openers(base_message, segments)

        assert len(openers) == 3
        assert set(openers.keys()) == set(segments)
        # Every opener should contain the base message
        for opener in openers.values():
            assert base_message in opener
        # Each segment should get a distinct opener
        assert len(set(openers.values())) == 3

    def test_single_segment(self):
        """Should return one opener when only one segment is provided."""
        engine = MassMessagingEngine(creator_id="creator_1")
        openers = engine.build_segment_openers("Hello!", ["chatty_fan"])

        assert openers == {"chatty_fan": "Hello!"}


class TestRateLimit:
    """Tests for validate_rate_limit and send_campaign rate enforcement."""

    def test_rate_limit_first_ok(self):
        """First campaign of the day should pass rate limit validation."""
        engine = MassMessagingEngine(creator_id="creator_rl1")
        assert engine.validate_rate_limit("creator_rl1") is True

    def test_rate_limit_second_ok(self):
        """Second campaign of the day should also pass."""
        engine = MassMessagingEngine(creator_id="creator_rl2")

        engine.send_campaign(
            content_id="c1",
            segments=["instant_buyer"],
            segment_openers={"instant_buyer": "Hey!"},
            preview_url="https://example.com/1",
        )
        assert engine.validate_rate_limit("creator_rl2") is True

    def test_rate_limit_third_blocked(self):
        """Third campaign of the day should be blocked by rate limiting."""
        engine = MassMessagingEngine(creator_id="creator_rl3")

        # First two should succeed
        engine.send_campaign(
            content_id="c1",
            segments=["instant_buyer"],
            segment_openers={"instant_buyer": "Hey!"},
            preview_url="https://example.com/1",
        )
        engine.send_campaign(
            content_id="c2",
            segments=["quiet_lurker"],
            segment_openers={"quiet_lurker": "Psst!"},
            preview_url="https://example.com/2",
        )

        # Rate limit should now be exhausted
        assert engine.validate_rate_limit("creator_rl3") is False

        # Third send_campaign should raise
        with pytest.raises(RuntimeError, match="Rate limit exceeded"):
            engine.send_campaign(
                content_id="c3",
                segments=["attention_seeker"],
                segment_openers={"attention_seeker": "Yo!"},
                preview_url="https://example.com/3",
            )

    def test_rate_limit_resets_next_day(self):
        """Rate limit should reset when a new day begins."""
        engine = MassMessagingEngine(creator_id="creator_rl4")

        # Send two campaigns today
        engine.send_campaign(
            content_id="c1",
            segments=["instant_buyer"],
            segment_openers={"instant_buyer": "Hey!"},
            preview_url="https://example.com/1",
        )
        engine.send_campaign(
            content_id="c2",
            segments=["quiet_lurker"],
            segment_openers={"quiet_lurker": "Psst!"},
            preview_url="https://example.com/2",
        )

        assert engine.validate_rate_limit("creator_rl4") is False

        # Simulate a new day by clearing today's counters
        engine._rate_limit_store.clear()

        # Now it should allow campaigns again
        assert engine.validate_rate_limit("creator_rl4") is True

        campaign = engine.send_campaign(
            content_id="c3",
            segments=["attention_seeker"],
            segment_openers={"attention_seeker": "Yo!"},
            preview_url="https://example.com/3",
        )
        assert campaign.content_id == "c3"

    def test_different_creators_have_separate_limits(self):
        """Rate limits are per-creator, not global."""
        engine_a = MassMessagingEngine(creator_id="creator_a")
        engine_b = MassMessagingEngine(creator_id="creator_b")

        # Exhaust creator_a's limit
        engine_a.send_campaign(
            content_id="a1",
            segments=["instant_buyer"],
            segment_openers={"instant_buyer": "Hey!"},
            preview_url="https://example.com/a1",
        )
        engine_a.send_campaign(
            content_id="a2",
            segments=["quiet_lurker"],
            segment_openers={"quiet_lurker": "Psst!"},
            preview_url="https://example.com/a2",
        )

        assert engine_a.validate_rate_limit("creator_a") is False
        # creator_b should still be fine
        assert engine_b.validate_rate_limit("creator_b") is True


class TestRequiresPreview:
    """Tests for the requires_preview method."""

    def test_requires_preview_always_true(self):
        """requires_preview() should always return True."""
        engine = MassMessagingEngine(creator_id="creator_preview")
        assert engine.requires_preview() is True

        # Should be True regardless of engine state
        engine.send_campaign(
            content_id="c1",
            segments=["instant_buyer"],
            segment_openers={"instant_buyer": "Hey!"},
            preview_url="https://example.com/1",
        )
        assert engine.requires_preview() is True
