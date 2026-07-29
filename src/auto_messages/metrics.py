"""Aggregate-only Auto Messages metrics and no-send eligibility previews."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import Engine, and_, func, select

from src.persistence.presence import PresenceRepository
from src.persistence.schema import (
    FAN_PRESENCE,
    INBOUND_MESSAGES,
    NATIVE_CAMPAIGNS,
    OUTBOX_MESSAGES,
)

from .settings import AutoMessagesSettings


class AutoMessagesMetrics:
    def __init__(self, engine: Engine, *, creator_id: str):
        self.engine = engine
        self.creator_id = creator_id
        self.presence = PresenceRepository(engine)

    def snapshot(self, settings: AutoMessagesSettings) -> dict:
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=30)
        statuses = {
            "sent": 0,
            "failed": 0,
            "delivery_unknown": 0,
            "pending": 0,
            "sending": 0,
        }
        by_trigger = {
            "online": dict(statuses),
            "stalled": dict(statuses),
        }
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(
                    OUTBOX_MESSAGES.c.trigger_source,
                    OUTBOX_MESSAGES.c.status,
                    func.count(OUTBOX_MESSAGES.c.id),
                )
                .where(
                    and_(
                        OUTBOX_MESSAGES.c.creator_id == self.creator_id,
                        OUTBOX_MESSAGES.c.trigger_source.in_(
                            ("online", "stalled")
                        ),
                        OUTBOX_MESSAGES.c.created_at >= since,
                    )
                )
                .group_by(
                    OUTBOX_MESSAGES.c.trigger_source,
                    OUTBOX_MESSAGES.c.status,
                )
            ).all()
            online_now = connection.execute(
                select(func.count(FAN_PRESENCE.c.fan_id)).where(
                    and_(
                        FAN_PRESENCE.c.creator_id == self.creator_id,
                        FAN_PRESENCE.c.status == "online",
                        FAN_PRESENCE.c.last_seen_at
                        >= now
                        - timedelta(
                            seconds=settings.online.online_window_seconds
                        ),
                    )
                )
            ).scalar_one()
            campaign_drafts = connection.execute(
                select(func.count(NATIVE_CAMPAIGNS.c.id)).where(
                    and_(
                        NATIVE_CAMPAIGNS.c.creator_id == self.creator_id,
                        NATIVE_CAMPAIGNS.c.operator_status == "draft",
                    )
                )
            ).scalar_one()
            proactive_pending = connection.execute(
                select(func.count(INBOUND_MESSAGES.c.id)).where(
                    and_(
                        INBOUND_MESSAGES.c.creator_id == self.creator_id,
                        INBOUND_MESSAGES.c.trigger_kind.in_(
                            ("online", "stalled")
                        ),
                        INBOUND_MESSAGES.c.status.in_(
                            ("pending", "processing")
                        ),
                    )
                )
            ).scalar_one()
        for trigger, status, count in rows:
            if trigger in by_trigger:
                by_trigger[trigger][str(status)] = int(count)
        total_sent = sum(item["sent"] for item in by_trigger.values())
        terminal = sum(
            item["sent"]
            + item["failed"]
            + item["delivery_unknown"]
            for item in by_trigger.values()
        )
        stalled_candidates = len(
            self.presence.stalled_candidates(
                self.creator_id,
                stalled_before=(
                    now
                    - timedelta(
                        hours=settings.stalled.stalled_after_hours
                    )
                ),
                limit=5000,
            )
        )
        return {
            "active_triggers": int(settings.online.enabled)
            + int(settings.stalled.enabled),
            "sent_30d": total_sent,
            "delivery_rate": (
                round((total_sent / terminal) * 100, 1)
                if terminal
                else None
            ),
            "online_now": int(online_now or 0),
            "stalled_candidates": stalled_candidates,
            "pending_work": int(proactive_pending or 0),
            "campaign_drafts": int(campaign_drafts or 0),
            "by_trigger": by_trigger,
            "estimated_presence_read_credits_per_day": (
                math.ceil(
                    86400 / settings.online.poll_interval_seconds
                )
                if settings.online.enabled
                else 0
            ),
            "window_started_at": since.isoformat(),
            "generated_at": now.isoformat(),
        }

    def preview(
        self,
        settings: AutoMessagesSettings,
        trigger: str,
    ) -> dict:
        if trigger not in {"online", "stalled"}:
            raise ValueError("unsupported trigger type")
        metrics = self.snapshot(settings)
        trigger_settings = getattr(settings, trigger)
        candidate_count = (
            metrics["online_now"]
            if trigger == "online"
            else metrics["stalled_candidates"]
        )
        return {
            "trigger": trigger,
            "effective_enabled": trigger_settings.enabled,
            "candidate_count": candidate_count,
            "maximum_next_hour": min(
                candidate_count,
                trigger_settings.max_per_hour,
            ),
            "maximum_next_day": min(
                candidate_count,
                trigger_settings.max_per_day,
            ),
            "pending_work": metrics["pending_work"],
            "estimated_presence_read_credits_per_day": (
                metrics["estimated_presence_read_credits_per_day"]
                if trigger == "online"
                else 0
            ),
            "no_messages_sent": True,
        }
