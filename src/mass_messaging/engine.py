"""Mass Messaging Engine.

Handles campaign creation, segment-based message personalization,
rate limiting (max 2 campaigns per creator per day), and preview enforcement.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Campaign:
    """A mass messaging campaign targeting fan segments.

    Attributes:
        campaign_id: Unique identifier (auto-generated if not provided).
        content_id: ID of the content being promoted.
        creator_id: The creator sending this campaign.
        segments: List of fan segment names being targeted.
        segment_openers: Per-segment personalized opening messages.
        preview_url: URL to the content preview.
        status: Campaign status ('draft' or 'sent').
        sent_at: When the campaign was sent.
    """

    content_id: str
    creator_id: str
    segments: list[str]
    segment_openers: dict[str, str]
    preview_url: str
    campaign_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "draft"
    sent_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MassMessagingEngine:
    """Engine for sending mass messaging campaigns with segmentation and rate limiting.

    Rate limit: max 2 campaigns per creator per calendar day.

    Attributes:
        creator_id: The creator this engine instance is scoped to.
        _rate_limit_store: Class-level dict mapping creator_id -> list of sent datetimes.
    """

    _rate_limit_store: dict[str, list[datetime]] = {}

    def __init__(self, creator_id: str) -> None:
        """Initialize the engine scoped to a specific creator.

        Args:
            creator_id: The creator identifier for rate-limit tracking.
        """
        self.creator_id = creator_id

    def _today_key(self) -> str:
        """Return today's date as an ISO date string (YYYY-MM-DD) in UTC."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _count_today(self, creator_id: str) -> int:
        """Count how many campaigns a creator has sent today."""
        today = self._today_key()
        sent = self._rate_limit_store.get(creator_id, [])
        return sum(1 for dt in sent if dt.strftime("%Y-%m-%d") == today)

    def validate_rate_limit(self, creator_id: str) -> bool:
        """Check whether a creator is within their daily rate limit.

        Args:
            creator_id: The creator to check.

        Returns:
            True if the creator can send another campaign today (under 2), False otherwise.
        """
        return self._count_today(creator_id) < 2

    def send_campaign(
        self,
        content_id: str,
        segments: list[str],
        segment_openers: dict[str, str],
        preview_url: str,
    ) -> Campaign:
        """Create and send a mass messaging campaign.

        Enforces the daily rate limit before sending.

        Args:
            content_id: ID of the content to promote.
            segments: Fan segments to target.
            segment_openers: Per-segment personalized opener messages.
            preview_url: URL to the content preview.

        Returns:
            A Campaign dataclass representing the sent campaign.

        Raises:
            RuntimeError: If the creator has exceeded their daily rate limit (2/day).
        """
        if not self.validate_rate_limit(self.creator_id):
            raise RuntimeError(
                f"Rate limit exceeded for creator '{self.creator_id}': "
                f"max 2 campaigns per day."
            )

        now = datetime.now(timezone.utc)
        if self.creator_id not in self._rate_limit_store:
            self._rate_limit_store[self.creator_id] = []
        self._rate_limit_store[self.creator_id].append(now)

        return Campaign(
            content_id=content_id,
            creator_id=self.creator_id,
            segments=segments,
            segment_openers=segment_openers,
            preview_url=preview_url,
            status="sent",
            sent_at=now,
        )

    def build_segment_openers(
        self, base_message: str, segments: list[str]
    ) -> dict[str, str]:
        """Build personalized openers for each fan segment.

        Each segment gets a distinct opener that includes the base message
        with a segment-appropriate prefix. A single segment receives the
        base message unchanged.

        Args:
            base_message: The core message to personalize.
            segments: Fan segment names to create openers for.

        Returns:
            A dict mapping each segment name to its personalized opener.
        """
        if len(segments) == 1:
            return {segments[0]: base_message}

        openers: dict[str, str] = {}
        templates: dict[str, str] = {
            "instant_buyer": "Hey bestie! {msg}",
            "quiet_lurker": "Psst, I've been thinking about you... {msg}",
            "attention_seeker": "You're gonna LOVE this! {msg}",
            "tester": "Trust me on this one 😘 {msg}",
            "chatty_fan": "OMG you need to see this! {msg}",
        }

        for segment in segments:
            template = templates.get(segment, "[{seg}] {msg}")
            openers[segment] = template.format(msg=base_message, seg=segment)

        return openers

    def requires_preview(self) -> bool:
        """Check whether a preview is required before sending.

        Always returns True — preview is mandatory for all campaigns.

        Returns:
            True.
        """
        return True
