"""Credit-bounded APIFansly FYP analytics normalization."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import math
import threading
from typing import Any, TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from ..apifansly_client import ApifanslyClient

HOUR_MS = 60 * 60 * 1000
DAY_MS = 24 * HOUR_MS
FYP_SOURCE_TYPE = 0
RANGE_DAYS = {"24h": 1, "7d": 7, "30d": 30}


class FypAnalyticsError(ValueError):
    """Safe operator-facing analytics error."""


def _number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _integer(value: Any) -> int:
    return max(0, int(_number(value)))


def _https_url(value: Any) -> str | None:
    text = str(value or "").strip()
    try:
        parsed = urlsplit(text)
    except ValueError:
        return None
    return text if parsed.scheme == "https" and parsed.netloc else None


def _first_value(row: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def _tag_key(row: dict[str, Any]) -> str:
    return str(
        _first_value(row, ("id", "tagId", "tag_id", "name", "tag", "label"))
        or ""
    ).strip()


def _tag_name(row: dict[str, Any]) -> str:
    return str(
        _first_value(row, ("name", "tagName", "tag", "label", "slug"))
        or ""
    ).strip().lstrip("#")


def _tag_views(row: dict[str, Any]) -> int:
    return _integer(
        _first_value(
            row,
            ("views", "fypViews", "viewCount", "count", "value"),
        )
    )


def _location_from_media(media: dict[str, Any]) -> str | None:
    candidates: list[Any] = []
    for variant in media.get("variants", []):
        if not isinstance(variant, dict):
            continue
        if not str(variant.get("mimetype", "")).startswith("image/"):
            continue
        for value in variant.get("locations", []):
            if isinstance(value, dict):
                candidates.append(value.get("location") or value.get("url"))
    if str(media.get("mimetype", "")).startswith("image/"):
        for value in media.get("locations", []):
            if isinstance(value, dict):
                candidates.append(value.get("location") or value.get("url"))
    for candidate in candidates:
        url = _https_url(candidate)
        if url:
            return url
    return None


class FypAnalyticsService:
    """Fetch and normalize the documented APIFansly analytics contract."""

    def __init__(
        self,
        *,
        client: "ApifanslyClient | None",
        cache_ttl: timedelta = timedelta(minutes=10),
    ):
        self.client = client
        self.cache_ttl = cache_ttl
        self._cache: dict[str, tuple[datetime, dict[str, Any]]] = {}
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self.client is not None

    @staticmethod
    def _range(
        range_key: str,
        *,
        after: str | None = None,
        before: str | None = None,
        now: datetime | None = None,
    ) -> tuple[datetime, datetime, int, str]:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        key = str(range_key or "24h").strip().lower()
        if key in RANGE_DAYS:
            end = current
            start = end - timedelta(days=RANGE_DAYS[key])
        elif key == "custom":
            try:
                start = datetime.fromisoformat(
                    str(after or "").replace("Z", "+00:00")
                )
                end = datetime.fromisoformat(
                    str(before or "").replace("Z", "+00:00")
                )
            except ValueError as exc:
                raise FypAnalyticsError(
                    "Choose a valid custom start and end date"
                ) from exc
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            start = start.astimezone(timezone.utc)
            end = end.astimezone(timezone.utc)
            if end <= start:
                raise FypAnalyticsError(
                    "Custom end date must be after the start date"
                )
            if end - start > timedelta(days=366):
                raise FypAnalyticsError(
                    "Custom analytics ranges are limited to 366 days"
                )
        else:
            raise FypAnalyticsError("Unsupported analytics range")

        span = end - start
        if span <= timedelta(days=2):
            period = HOUR_MS
        elif span <= timedelta(days=14):
            period = 6 * HOUR_MS
        else:
            period = DAY_MS
        cache_key = (
            f"{key}:{int(start.timestamp())}:{int(end.timestamp())}:{period}"
            if key == "custom"
            else key
        )
        return start, end, period, cache_key

    def snapshot(
        self,
        range_key: str = "24h",
        *,
        after: str | None = None,
        before: str | None = None,
        force_refresh: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if self.client is None:
            return {
                "available": False,
                "reason": "APIFansly analytics credentials are not configured",
                "range": range_key,
            }
        start, end, period, cache_key = self._range(
            range_key,
            after=after,
            before=before,
            now=now,
        )
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        with self._lock:
            cached = self._cache.get(cache_key)
            if (
                not force_refresh
                and cached is not None
                and current - cached[0] < self.cache_ttl
            ):
                result = dict(cached[1])
                result["cached"] = True
                return result

            try:
                raw = self.client.get_profile_statistics(
                    after_date=int(start.timestamp() * 1000),
                    before_date=int(end.timestamp() * 1000),
                    period=period,
                )
            except Exception as exc:
                raise FypAnalyticsError(
                    "APIFansly could not load profile analytics"
                ) from exc
            result = self._normalize(
                raw,
                range_key=range_key,
                start=start,
                end=end,
                period=period,
                fetched_at=current,
            )
            self._cache[cache_key] = (current, result)
            return dict(result)

    @staticmethod
    def _normalize(
        raw: dict[str, Any],
        *,
        range_key: str,
        start: datetime,
        end: datetime,
        period: int,
        fetched_at: datetime,
    ) -> dict[str, Any]:
        dataset = raw.get("dataset", {})
        if not isinstance(dataset, dict):
            raise FypAnalyticsError(
                "APIFansly analytics did not include a dataset"
            )
        aggregation = raw.get("aggregationData", {})
        if not isinstance(aggregation, dict):
            aggregation = {}

        timeline: list[dict[str, Any]] = []
        source_totals: dict[int, dict[str, float]] = defaultdict(
            lambda: {
                "views": 0,
                "interaction_time": 0,
                "unique_viewers": 0,
                "video_views": 0,
                "video_percent_watched": 0,
            }
        )
        all_totals = {
            "views": 0.0,
            "interaction_time": 0.0,
            "unique_viewers": 0.0,
            "video_views": 0.0,
            "video_percent_watched": 0.0,
        }
        for point in dataset.get("datapoints", []):
            if not isinstance(point, dict):
                continue
            try:
                timestamp = int(point.get("timestamp"))
            except (TypeError, ValueError):
                continue
            fyp = {
                "views": 0.0,
                "interaction_time": 0.0,
                "unique_viewers": 0.0,
                "video_views": 0.0,
                "video_percent_watched": 0.0,
            }
            for stat in point.get("stats", []):
                if not isinstance(stat, dict):
                    continue
                try:
                    source_type = int(stat.get("type"))
                except (TypeError, ValueError):
                    continue
                values = {
                    "views": _number(stat.get("views")),
                    "interaction_time": _number(
                        stat.get("interactionTime")
                    ),
                    "unique_viewers": _number(
                        stat.get("uniqueViewers")
                    ),
                    "video_views": _number(stat.get("videoViews")),
                    "video_percent_watched": _number(
                        stat.get("totalVideoPercentWatched")
                    ),
                }
                for name, value in values.items():
                    source_totals[source_type][name] += value
                    all_totals[name] += value
                    if source_type == FYP_SOURCE_TYPE:
                        fyp[name] += value
            timeline.append(
                {
                    "timestamp": timestamp,
                    "views": _integer(fyp["views"]),
                    "unique_viewers": _integer(fyp["unique_viewers"]),
                    "avg_engagement_seconds": round(
                        fyp["interaction_time"]
                        / max(1.0, fyp["unique_viewers"])
                        / 1000,
                        2,
                    ),
                }
            )

        fyp_totals = source_totals[FYP_SOURCE_TYPE]
        fyp_views = _integer(fyp_totals["views"])
        fyp_unique = _integer(fyp_totals["unique_viewers"])
        avg_engagement = round(
            fyp_totals["interaction_time"]
            / max(1.0, fyp_totals["unique_viewers"])
            / 1000,
            2,
        )
        reach_rate = round(
            fyp_totals["unique_viewers"]
            * 100
            / max(1.0, all_totals["unique_viewers"]),
            1,
        )
        avg_watch_percent = round(
            fyp_totals["video_percent_watched"]
            / max(1.0, fyp_totals["video_views"]),
            1,
        )

        tag_lookup: dict[str, str] = {}
        for tag in aggregation.get("tags", []):
            if not isinstance(tag, dict):
                continue
            key, name = _tag_key(tag), _tag_name(tag)
            if key and name:
                tag_lookup[key] = name
        tags: list[dict[str, Any]] = []
        for index, item in enumerate(dataset.get("topFypTags", [])):
            if isinstance(item, str):
                name, views = item.lstrip("#"), 0
            elif isinstance(item, dict):
                key = _tag_key(item)
                name = _tag_name(item) or tag_lookup.get(key, "")
                views = _tag_views(item)
            else:
                continue
            if not name:
                name = f"tag-{index + 1}"
            tags.append({"name": name[:80], "views": views})
        tags.sort(key=lambda row: row["views"], reverse=True)
        tagged_views = sum(row["views"] for row in tags)
        tag_ratio = round(tagged_views * 100 / max(1, fyp_views), 1)

        media_by_id: dict[str, dict[str, Any]] = {}
        for item in aggregation.get("accountMedia", []):
            if not isinstance(item, dict):
                continue
            media = item.get("media", {})
            if not isinstance(media, dict):
                continue
            metadata = {
                "thumbnail_url": _location_from_media(media),
                "media_type": str(
                    media.get("mimetype") or "media"
                ).split("/", 1)[0],
                "created_at": item.get("createdAt"),
            }
            identifiers = {
                str(item.get("id") or "").strip(),
                str(item.get("mediaId") or "").strip(),
                str(media.get("id") or "").strip(),
            }
            for identifier in identifiers:
                if identifier:
                    media_by_id[identifier] = metadata
        offer_locations: dict[str, str] = {}
        for item in aggregation.get("creatorMediaOfferLocations", []):
            if not isinstance(item, dict):
                continue
            offer_id = str(
                _first_value(item, ("mediaOfferId", "offerId", "id")) or ""
            )
            account_media_id = str(
                _first_value(
                    item,
                    ("accountMediaId", "mediaId", "locationId"),
                )
                or ""
            )
            if offer_id and account_media_id:
                offer_locations[offer_id] = account_media_id

        media_rows: list[dict[str, Any]] = []
        for index, item in enumerate(dataset.get("topFypMediaOffers", [])):
            if not isinstance(item, dict):
                continue
            offer_id = str(
                _first_value(item, ("mediaOfferId", "id", "offerId")) or ""
            )
            account_media_id = str(
                _first_value(item, ("accountMediaId", "mediaId")) or ""
            )
            metadata = media_by_id.get(
                account_media_id
                or offer_locations.get(offer_id, "")
                or offer_id,
                {},
            )
            views = _integer(
                _first_value(item, ("views", "fypViews", "viewCount"))
            )
            unique = _integer(
                _first_value(item, ("uniqueViewers", "uniqueViews"))
            )
            interaction_ms = _number(
                _first_value(item, ("interactionTime", "watchTime"))
            )
            divisor = unique or views
            media_rows.append(
                {
                    "rank": index + 1,
                    "views": views,
                    "unique_viewers": unique,
                    "avg_engagement_seconds": round(
                        interaction_ms / max(1, divisor) / 1000,
                        2,
                    ),
                    "thumbnail_url": metadata.get("thumbnail_url"),
                    "media_type": metadata.get("media_type", "media"),
                }
            )
        media_rows.sort(key=lambda row: row["views"], reverse=True)
        for index, row in enumerate(media_rows):
            row["rank"] = index + 1

        by_hour: dict[int, dict[str, int]] = defaultdict(
            lambda: {"views": 0, "buckets": 0}
        )
        by_weekday: dict[int, dict[str, int]] = defaultdict(
            lambda: {"views": 0, "buckets": 0}
        )
        for point in timeline:
            stamp = datetime.fromtimestamp(
                point["timestamp"] / 1000,
                tz=timezone.utc,
            )
            by_hour[stamp.hour]["views"] += point["views"]
            by_hour[stamp.hour]["buckets"] += 1
            by_weekday[stamp.weekday()]["views"] += point["views"]
            by_weekday[stamp.weekday()]["buckets"] += 1
        best_hours = sorted(
            (
                {
                    "hour_utc": hour,
                    "avg_views": round(
                        values["views"] / max(1, values["buckets"]),
                        1,
                    ),
                }
                for hour, values in by_hour.items()
            ),
            key=lambda row: row["avg_views"],
            reverse=True,
        )[:6]
        weekdays = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                    "Saturday", "Sunday")
        best_days = sorted(
            (
                {
                    "day": weekdays[day],
                    "avg_views": round(
                        values["views"] / max(1, values["buckets"]),
                        1,
                    ),
                }
                for day, values in by_weekday.items()
            ),
            key=lambda row: row["avg_views"],
            reverse=True,
        )[:7]

        recommendations: list[str] = []
        if not fyp_views:
            recommendations.append(
                "No FYP views were returned for this range. Confirm posts are "
                "opted into FYP and include a free preview when media is locked."
            )
        if fyp_views and avg_engagement < 2:
            recommendations.append(
                "FYP engagement is under 2 seconds per unique viewer. Test a "
                "stronger first frame and a shorter preview."
            )
        if fyp_totals["video_views"] and avg_watch_percent < 35:
            recommendations.append(
                "Average video completion is below 35%. Shorten the opening "
                "clip or move the payoff earlier."
            )
        if fyp_views and not tags:
            recommendations.append(
                "FYP traffic is present but APIFansly returned no top tags. "
                "Use a small consistent tag set so attribution can accumulate."
            )
        if tags:
            recommendations.append(
                "Reuse the strongest FYP tag only when it accurately describes "
                "the next post; avoid copying the full tag set every time."
            )
        if not recommendations:
            recommendations.append(
                "The current FYP baseline is healthy. Keep the format stable "
                "and change one hook or tag variable per test."
            )

        return {
            "available": True,
            "provider": "APIFansly",
            "range": range_key,
            "after": start.isoformat(),
            "before": end.isoformat(),
            "period_ms": period,
            "fetched_at": fetched_at.isoformat(),
            "cached": False,
            "metrics": {
                "fyp_views": fyp_views,
                "unique_fyp_viewers": fyp_unique,
                "avg_fyp_engagement_seconds": avg_engagement,
                "fyp_reach_rate": reach_rate,
                "tag_fyp_views": tagged_views,
                "tag_fyp_ratio": tag_ratio,
                "avg_video_watched_percent": avg_watch_percent,
            },
            "timeline": sorted(
                timeline,
                key=lambda row: row["timestamp"],
            ),
            "tags": tags[:30],
            "media": media_rows[:30],
            "best_times": {
                "timezone": "UTC",
                "hours": best_hours,
                "days": best_days,
            },
            "recommendations": recommendations[:5],
            "definitions": {
                "avg_fyp_engagement_seconds": (
                    "FYP interaction time divided by FYP unique viewers"
                ),
                "fyp_reach_rate": (
                    "FYP unique viewers divided by all media unique viewers"
                ),
                "tag_fyp_ratio": (
                    "sum of APIFansly top-tag FYP views divided by FYP views; "
                    "one view may be attributed to multiple tags"
                ),
            },
        }
