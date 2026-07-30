from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, insert

from src.fyp_analytics import FypAnalyticsError, FypAnalyticsService
from src.persistence.schema import CREATORS, metadata
from src.provider_read_cache import ProviderReadCache


def _provider_response():
    timestamp = int(
        datetime(2026, 7, 30, 8, tzinfo=timezone.utc).timestamp() * 1000
    )
    return {
        "dataset": {
            "datapoints": [
                {
                    "timestamp": timestamp,
                    "stats": [
                        {
                            "type": 0,
                            "views": 100,
                            "interactionTime": 250000,
                            "uniqueViewers": 50,
                            "videoViews": 100,
                            "totalVideoPercentWatched": 7500,
                        },
                        {
                            "type": 1,
                            "views": 80,
                            "interactionTime": 60000,
                            "uniqueViewers": 50,
                            "videoViews": 20,
                            "totalVideoPercentWatched": 1000,
                        },
                    ],
                }
            ],
            "topFypTags": [
                {"tagId": "tag-1", "views": 80},
                {"tagId": "tag-2", "views": 20},
            ],
            "topFypMediaOffers": [
                {
                    "mediaOfferId": "offer-1",
                    "views": 90,
                    "uniqueViewers": 45,
                    "interactionTime": 180000,
                    "tagIds": ["tag-1", "tag-2"],
                }
            ],
        },
        "aggregationData": {
            "tags": [
                {"id": "tag-1", "name": "cosplay"},
                {"id": "tag-2", "name": "fyp"},
            ],
            "creatorMediaOfferLocations": [
                {
                    "mediaOfferId": "offer-1",
                    "accountMediaId": "media-1",
                }
            ],
            "accountMedia": [
                {
                    "id": "media-1",
                    "media": {
                        "mimetype": "video/mp4",
                        "locations": [
                            {"location": "https://cdn.example/fyp.mp4"}
                        ],
                        "variants": [
                            {
                                "mimetype": "image/jpeg",
                                "locations": [
                                    {
                                        "location": (
                                            "https://cdn.example/fyp.jpg"
                                        )
                                    }
                                ],
                            }
                        ],
                    },
                }
            ],
        },
    }


def test_normalizes_real_fyp_tag_media_and_time_metrics():
    client = MagicMock()
    client.get_profile_statistics.return_value = _provider_response()
    service = FypAnalyticsService(client=client)
    now = datetime(2026, 7, 30, 10, tzinfo=timezone.utc)

    result = service.snapshot("24h", now=now)

    assert result["provider"] == "APIFansly"
    assert result["metrics"] == {
        "fyp_views": 100,
        "unique_fyp_viewers": 50,
        "avg_fyp_engagement_seconds": 5.0,
        "fyp_reach_rate": 50.0,
        "tag_fyp_views": 100,
        "tag_fyp_ratio": 100.0,
        "avg_video_watched_percent": 75.0,
    }
    assert result["tags"] == [
        {"name": "cosplay", "views": 80},
        {"name": "fyp", "views": 20},
    ]
    assert result["media"][0] == {
        "rank": 1,
        "views": 90,
        "unique_viewers": 45,
        "avg_engagement_seconds": 4.0,
        "thumbnail_url": "https://cdn.example/fyp.jpg",
        "playback_url": "https://cdn.example/fyp.mp4",
        "media_type": "video",
        "hashtags": ["cosplay", "fyp"],
    }
    assert result["best_times"]["hours"][0] == {
        "hour_utc": 8,
        "avg_views": 100.0,
    }
    assert "offer-1" not in str(result)
    assert "media-1" not in str(result)


def test_matches_fyp_offer_to_account_media_provider_media_id():
    response = _provider_response()
    response["dataset"]["topFypMediaOffers"][0]["mediaOfferId"] = (
        "provider-media-1"
    )
    response["aggregationData"]["creatorMediaOfferLocations"] = []
    account_media = response["aggregationData"]["accountMedia"][0]
    account_media["id"] = "account-media-1"
    account_media["mediaId"] = "provider-media-1"

    client = MagicMock()
    client.get_profile_statistics.return_value = response
    service = FypAnalyticsService(client=client)

    result = service.snapshot(
        "24h",
        now=datetime(2026, 7, 30, 10, tzinfo=timezone.utc),
    )

    assert result["media"][0]["thumbnail_url"] == (
        "https://cdn.example/fyp.jpg"
    )
    assert result["media"][0]["playback_url"] == (
        "https://cdn.example/fyp.mp4"
    )
    assert result["media"][0]["media_type"] == "video"


def test_does_not_assign_range_tags_to_media_without_provider_mapping():
    response = _provider_response()
    response["dataset"]["topFypMediaOffers"][0].pop("tagIds")
    client = MagicMock()
    client.get_profile_statistics.return_value = response
    service = FypAnalyticsService(client=client)

    result = service.snapshot(
        "24h",
        now=datetime(2026, 7, 30, 10, tzinfo=timezone.utc),
    )

    assert result["tags"]
    assert result["media"][0]["hashtags"] == []


def test_caches_each_range_for_ten_minutes_and_force_refreshes():
    client = MagicMock()
    client.get_profile_statistics.return_value = _provider_response()
    service = FypAnalyticsService(
        client=client,
        cache_ttl=timedelta(minutes=10),
    )
    now = datetime(2026, 7, 30, 10, tzinfo=timezone.utc)

    first = service.snapshot("7d", now=now)
    cached = service.snapshot("7d", now=now + timedelta(minutes=5))
    refreshed = service.snapshot(
        "7d",
        force_refresh=True,
        now=now + timedelta(minutes=6),
    )

    assert first["cached"] is False
    assert cached["cached"] is True
    assert refreshed["cached"] is False
    assert client.get_profile_statistics.call_count == 2
    params = client.get_profile_statistics.call_args.kwargs
    assert params["period"] == 6 * 60 * 60 * 1000


def test_durable_cache_survives_service_restart_without_signed_urls():
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    now = datetime(2026, 7, 30, 10, tzinfo=timezone.utc)
    with engine.begin() as connection:
        connection.execute(
            insert(CREATORS).values(
                id="creator-1",
                created_at=now,
                updated_at=now,
            )
        )
    read_cache = ProviderReadCache(engine, creator_id="creator-1")
    first_client = MagicMock()
    first_client.get_profile_statistics.return_value = _provider_response()
    first_service = FypAnalyticsService(
        client=first_client,
        read_cache=read_cache,
    )

    fresh = first_service.snapshot("24h", now=now)
    second_client = MagicMock()
    second_service = FypAnalyticsService(
        client=second_client,
        read_cache=read_cache,
    )
    durable = second_service.snapshot(
        "24h",
        now=now + timedelta(minutes=5),
    )

    assert fresh["media"][0]["thumbnail_url"].startswith("https://")
    assert durable["cache_layer"] == "durable"
    assert durable["provider_request_made"] is False
    assert durable["media"][0]["thumbnail_url"] is None
    assert durable["media"][0]["playback_url"] is None
    assert durable["media_thumbnails_available"] is False
    second_client.get_profile_statistics.assert_not_called()


def test_forced_refresh_has_one_minute_provider_cooldown():
    client = MagicMock()
    client.get_profile_statistics.return_value = _provider_response()
    service = FypAnalyticsService(client=client)
    now = datetime(2026, 7, 30, 10, tzinfo=timezone.utc)

    service.snapshot("24h", now=now)
    result = service.snapshot(
        "24h",
        force_refresh=True,
        now=now + timedelta(seconds=10),
    )

    assert result["provider_request_made"] is False
    assert result["refresh_cooldown_seconds"] == 50
    assert client.get_profile_statistics.call_count == 1


def test_custom_range_validation_is_bounded():
    service = FypAnalyticsService(client=MagicMock())

    with pytest.raises(FypAnalyticsError, match="after the start"):
        service.snapshot(
            "custom",
            after="2026-07-30T10:00:00+00:00",
            before="2026-07-30T09:00:00+00:00",
        )

    with pytest.raises(FypAnalyticsError, match="366 days"):
        service.snapshot(
            "custom",
            after="2025-01-01T00:00:00+00:00",
            before="2026-07-30T00:00:00+00:00",
        )


def test_unconfigured_service_is_explicit_and_does_not_fake_metrics():
    service = FypAnalyticsService(client=None)

    result = service.snapshot("24h")

    assert result["available"] is False
    assert "credentials" in result["reason"]
    assert "metrics" not in result
