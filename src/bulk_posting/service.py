"""Durable APIFansly post scheduling with bounded recurrence handling."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import os
import re
from typing import Any

from sqlalchemy import and_, case, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from ..apifansly_client import ApifanslyClient
from .schema import BULK_POST_OCCURRENCES, BULK_POST_RULES

logger = logging.getLogger("fansly-bot.bulk-posting")

TAG_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,50}$")
RECURRENCES = {"one_time", "daily", "weekly", "monthly"}


class BulkPostingError(ValueError):
    """Safe operator-facing bulk-posting error."""


@dataclass(frozen=True)
class UploadedPostMedia:
    name: str
    media_type: str
    media_id: str
    account_media_id: str

    def as_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "media_type": self.media_type,
            "media_id": self.media_id,
            "account_media_id": self.account_media_id,
        }


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _next_occurrence(value: datetime, recurrence: str) -> datetime | None:
    if recurrence == "one_time":
        return None
    if recurrence == "daily":
        return value + timedelta(days=1)
    if recurrence == "weekly":
        return value + timedelta(days=7)
    if recurrence == "monthly":
        year = value.year + (1 if value.month == 12 else 0)
        month = 1 if value.month == 12 else value.month + 1
        day = min(value.day, calendar.monthrange(year, month)[1])
        return value.replace(year=year, month=month, day=day)
    raise BulkPostingError("Unsupported recurrence")


class BulkPostingService:
    """Schedules documented APIFansly posts without changing the chat provider."""

    def __init__(
        self,
        engine,
        *,
        creator_id: str,
        client: ApifanslyClient | None,
        submit_horizon: timedelta = timedelta(hours=24),
    ):
        self.engine = engine
        self.creator_id = creator_id
        self.client = client
        self.submit_horizon = submit_horizon
        self._walls_cache: list[dict[str, str]] = []
        self._walls_cached_at: datetime | None = None

    @property
    def available(self) -> bool:
        return self.client is not None

    def safe_status(self) -> dict[str, Any]:
        reason = ""
        if self.client is None:
            reason = (
                "APIFansly posting credentials are not configured. "
                "Chat remains connected through the existing provider."
            )
        return {
            "available": self.available,
            "reason": reason,
            "paid_preview_supported": False,
            "paid_preview_reason": (
                "The documented Fansly create-post API does not expose "
                "paid-preview configuration."
            ),
        }

    def walls(self) -> list[dict[str, str]]:
        if self.client is None:
            return []
        now = datetime.now(timezone.utc)
        if (
            self._walls_cached_at is None
            or now - self._walls_cached_at > timedelta(minutes=5)
        ):
            self._walls_cache = self.client.list_post_walls()
            self._walls_cached_at = now
        return list(self._walls_cache)

    def upload_media(
        self,
        file_path: str,
        *,
        original_name: str,
        media_type: str,
    ) -> dict[str, str]:
        if self.client is None:
            raise BulkPostingError("Bulk posting is not configured")
        result = self.client.upload_post_media(file_path)
        return UploadedPostMedia(
            name=os.path.basename(original_name)[:255],
            media_type=media_type,
            media_id=result["media_id"],
            account_media_id=result["account_media_id"],
        ).as_dict()

    @staticmethod
    def normalize_tags(values: list[Any]) -> list[str]:
        tags: list[str] = []
        for value in values:
            tag = str(value).strip().lstrip("#")
            if not tag:
                continue
            if not TAG_PATTERN.fullmatch(tag):
                raise BulkPostingError(
                    "Tags may contain only letters, numbers, and underscores"
                )
            normalized = tag.lower()
            if normalized not in tags:
                tags.append(normalized)
        return tags[:30]

    @staticmethod
    def post_content(caption: str, tags: list[str]) -> str:
        clean_caption = str(caption).strip()
        hashtag_line = " ".join(f"#{tag}" for tag in tags)
        return "\n\n".join(
            value for value in (clean_caption, hashtag_line) if value
        )

    def _validate_schedule(self, payload: dict[str, Any]) -> dict[str, Any]:
        recurrence = str(payload.get("recurrence", "one_time")).strip()
        if recurrence not in RECURRENCES:
            raise BulkPostingError("Unsupported recurrence")
        try:
            scheduled_for = _utc(
                datetime.fromisoformat(
                    str(payload["scheduled_for"]).replace("Z", "+00:00")
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BulkPostingError("A valid schedule time is required") from exc
        if scheduled_for < datetime.now(timezone.utc) - timedelta(minutes=1):
            raise BulkPostingError("Schedule time cannot be in the past")

        expires_at = None
        if payload.get("expires_at"):
            try:
                expires_at = _utc(
                    datetime.fromisoformat(
                        str(payload["expires_at"]).replace("Z", "+00:00")
                    )
                )
            except (TypeError, ValueError) as exc:
                raise BulkPostingError("Expires-at time is invalid") from exc
            if expires_at <= scheduled_for:
                raise BulkPostingError(
                    "Expires-at time must be after the schedule time"
                )

        wall_ids = [
            str(value).strip()
            for value in payload.get("wall_ids", [])
            if str(value).strip()
        ]
        if not wall_ids:
            raise BulkPostingError("Select at least one wall")
        media = [
            value
            for value in payload.get("media", [])
            if isinstance(value, dict)
            and str(value.get("account_media_id", "")).strip()
        ]
        caption = str(payload.get("caption", "")).strip()
        tags = self.normalize_tags(payload.get("tags", []))
        if not caption and not media:
            raise BulkPostingError("Add a caption or media")
        if bool(payload.get("paid_preview", False)):
            raise BulkPostingError(
                "Paid-post preview is not supported by the documented provider API"
            )
        return {
            "caption": caption,
            "tags": tags,
            "wall_ids": wall_ids,
            "media": media,
            "recurrence": recurrence,
            "carousel": bool(payload.get("carousel", False)),
            "paid_preview": False,
            "scheduled_for": scheduled_for,
            "expires_at": expires_at,
        }

    def schedule(
        self,
        payload: dict[str, Any],
        *,
        actor: str = "owner",
    ) -> dict[str, Any]:
        if self.client is None:
            raise BulkPostingError("Bulk posting is not configured")
        values = self._validate_schedule(payload)
        now = datetime.now(timezone.utc)
        next_run = _next_occurrence(
            values["scheduled_for"],
            values["recurrence"],
        )
        with self.engine.begin() as connection:
            rule_id = connection.execute(
                insert(BULK_POST_RULES)
                .values(
                    creator_id=self.creator_id,
                    created_by=str(actor).strip()[:128] or "owner",
                    caption=values["caption"],
                    tags=values["tags"],
                    wall_ids=values["wall_ids"],
                    media=values["media"],
                    recurrence=values["recurrence"],
                    carousel=values["carousel"],
                    paid_preview=False,
                    first_scheduled_for=values["scheduled_for"],
                    expires_at=values["expires_at"],
                    next_scheduled_for=next_run,
                    status=(
                        "recurring"
                        if values["recurrence"] != "one_time"
                        else "scheduled"
                    ),
                    created_at=now,
                    updated_at=now,
                )
                .returning(BULK_POST_RULES.c.id)
            ).scalar_one()
        occurrence_ids = self._submit_rule_occurrence(
            int(rule_id),
            values,
            values["scheduled_for"],
            values["expires_at"],
        )
        return {
            "rule_id": int(rule_id),
            "occurrence_ids": occurrence_ids,
            "status": "scheduled",
        }

    def _submit_rule_occurrence(
        self,
        rule_id: int,
        values: dict[str, Any],
        scheduled_for: datetime,
        expires_at: datetime | None,
    ) -> list[int]:
        media = values["media"]
        groups = (
            [media]
            if values["carousel"] or len(media) <= 1
            else [[item] for item in media]
        )
        if not groups:
            groups = [[]]
        occurrence_ids: list[int] = []
        for occurrence_index, group in enumerate(groups):
            occurrence_ids.append(
                self._submit_one(
                    rule_id,
                    values,
                    group,
                    occurrence_index,
                    scheduled_for,
                    expires_at,
                )
            )
        return occurrence_ids

    def _submit_one(
        self,
        rule_id: int,
        values: dict[str, Any],
        media: list[dict[str, Any]],
        occurrence_index: int,
        scheduled_for: datetime,
        expires_at: datetime | None,
    ) -> int:
        now = datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            occurrence_id = connection.execute(
                insert(BULK_POST_OCCURRENCES)
                .values(
                    rule_id=rule_id,
                    creator_id=self.creator_id,
                    occurrence_index=occurrence_index,
                    scheduled_for=scheduled_for,
                    expires_at=expires_at,
                    status="submitting",
                    attempt_count=1,
                    created_at=now,
                    updated_at=now,
                )
                .returning(BULK_POST_OCCURRENCES.c.id)
            ).scalar_one()
        try:
            post = self.client.create_post(
                content=self.post_content(values["caption"], values["tags"]),
                wall_ids=values["wall_ids"],
                account_media_ids=[
                    str(item["account_media_id"]) for item in media
                ],
                scheduled_for=int(scheduled_for.timestamp()),
                expires_at=(
                    int(expires_at.timestamp()) if expires_at is not None else 0
                ),
            )
        except Exception as exc:
            error_code = type(exc).__name__[:64]
            with self.engine.begin() as connection:
                connection.execute(
                    update(BULK_POST_OCCURRENCES)
                    .where(BULK_POST_OCCURRENCES.c.id == occurrence_id)
                    .values(
                        status="delivery_unknown",
                        error_code=error_code,
                        updated_at=datetime.now(timezone.utc),
                    )
                )
                connection.execute(
                    update(BULK_POST_RULES)
                    .where(BULK_POST_RULES.c.id == rule_id)
                    .values(
                        status="attention_required",
                        last_error_code=error_code,
                        updated_at=datetime.now(timezone.utc),
                    )
                )
            logger.warning(
                "Bulk post submission needs operator review: %s",
                error_code,
            )
            raise BulkPostingError(
                "The provider did not confirm the scheduled post; "
                "it was not retried automatically"
            ) from exc
        submitted_at = datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            connection.execute(
                update(BULK_POST_OCCURRENCES)
                .where(BULK_POST_OCCURRENCES.c.id == occurrence_id)
                .values(
                    provider_post_id=post["id"],
                    status="submitted",
                    submitted_at=submitted_at,
                    updated_at=submitted_at,
                )
            )
        return int(occurrence_id)

    def run_due(self, *, now: datetime | None = None, limit: int = 20) -> int:
        if self.client is None:
            return 0
        now = _utc(now or datetime.now(timezone.utc))
        due_before = now + self.submit_horizon
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(BULK_POST_RULES)
                .where(
                    and_(
                        BULK_POST_RULES.c.creator_id == self.creator_id,
                        BULK_POST_RULES.c.status == "recurring",
                        BULK_POST_RULES.c.next_scheduled_for.is_not(None),
                        BULK_POST_RULES.c.next_scheduled_for <= due_before,
                    )
                )
                .order_by(BULK_POST_RULES.c.next_scheduled_for)
                .limit(max(1, min(int(limit), 100)))
            ).mappings().all()
        submitted = 0
        for row in rows:
            scheduled_for = _utc(row["next_scheduled_for"])
            values = {
                "caption": row["caption"],
                "tags": list(row["tags"] or []),
                "wall_ids": list(row["wall_ids"] or []),
                "media": list(row["media"] or []),
                "carousel": bool(row["carousel"]),
            }
            expires_at = None
            if row["expires_at"] is not None:
                expiry_delta = _utc(row["expires_at"]) - _utc(
                    row["first_scheduled_for"]
                )
                expires_at = scheduled_for + expiry_delta
            try:
                self._submit_rule_occurrence(
                    int(row["id"]),
                    values,
                    scheduled_for,
                    expires_at,
                )
            except (BulkPostingError, IntegrityError):
                continue
            following = _next_occurrence(scheduled_for, str(row["recurrence"]))
            with self.engine.begin() as connection:
                connection.execute(
                    update(BULK_POST_RULES)
                    .where(
                        and_(
                            BULK_POST_RULES.c.id == row["id"],
                            BULK_POST_RULES.c.next_scheduled_for
                            == row["next_scheduled_for"],
                        )
                    )
                    .values(
                        next_scheduled_for=following,
                        updated_at=datetime.now(timezone.utc),
                    )
                )
            submitted += 1
        return submitted

    def snapshot(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=30)
        with self.engine.connect() as connection:
            scheduled_count = connection.execute(
                select(func.count())
                .select_from(BULK_POST_OCCURRENCES)
                .where(
                    and_(
                        BULK_POST_OCCURRENCES.c.creator_id == self.creator_id,
                        BULK_POST_OCCURRENCES.c.status == "submitted",
                        BULK_POST_OCCURRENCES.c.scheduled_for >= now,
                    )
                )
            ).scalar_one()
            next_post = connection.execute(
                select(func.min(BULK_POST_OCCURRENCES.c.scheduled_for)).where(
                    and_(
                        BULK_POST_OCCURRENCES.c.creator_id == self.creator_id,
                        BULK_POST_OCCURRENCES.c.status == "submitted",
                        BULK_POST_OCCURRENCES.c.scheduled_for >= now,
                    )
                )
            ).scalar_one()
            recurring_count = connection.execute(
                select(func.count())
                .select_from(BULK_POST_RULES)
                .where(
                    and_(
                        BULK_POST_RULES.c.creator_id == self.creator_id,
                        BULK_POST_RULES.c.status == "recurring",
                    )
                )
            ).scalar_one()
            delivery = connection.execute(
                select(
                    func.count(),
                    func.sum(
                        case(
                            (
                                BULK_POST_OCCURRENCES.c.status == "submitted",
                                1,
                            ),
                            else_=0,
                        )
                    ),
                ).where(
                    and_(
                        BULK_POST_OCCURRENCES.c.creator_id == self.creator_id,
                        BULK_POST_OCCURRENCES.c.created_at >= cutoff,
                        BULK_POST_OCCURRENCES.c.status.in_(
                            ["submitted", "delivery_unknown"]
                        ),
                    )
                )
            ).one()
            rows = connection.execute(
                select(
                    BULK_POST_OCCURRENCES.c.id,
                    BULK_POST_OCCURRENCES.c.scheduled_for,
                    BULK_POST_OCCURRENCES.c.status,
                    BULK_POST_OCCURRENCES.c.provider_post_id,
                    BULK_POST_RULES.c.caption,
                    BULK_POST_RULES.c.tags,
                    BULK_POST_RULES.c.recurrence,
                    BULK_POST_RULES.c.media,
                )
                .join(
                    BULK_POST_RULES,
                    BULK_POST_RULES.c.id
                    == BULK_POST_OCCURRENCES.c.rule_id,
                )
                .where(
                    BULK_POST_OCCURRENCES.c.creator_id == self.creator_id
                )
                .order_by(BULK_POST_OCCURRENCES.c.scheduled_for.desc())
                .limit(100)
            ).mappings().all()
        total = int(delivery[0] or 0)
        successful = int(delivery[1] or 0)
        status = self.safe_status()
        status.update(
            {
                "walls": self.walls() if self.available else [],
                "metrics": {
                    "scheduled_posts": int(scheduled_count or 0),
                    "next_post": next_post.isoformat() if next_post else None,
                    "recurring_rules": int(recurring_count or 0),
                    "delivery_rate": (
                        round(successful * 100 / total, 1) if total else None
                    ),
                },
                "posts": [
                    {
                        "id": int(row["id"]),
                        "scheduled_for": row["scheduled_for"].isoformat(),
                        "status": row["status"],
                        "provider_post_id": row["provider_post_id"],
                        "caption": row["caption"],
                        "tags": list(row["tags"] or []),
                        "recurrence": row["recurrence"],
                        "media_count": len(row["media"] or []),
                    }
                    for row in rows
                ],
            }
        )
        return status
