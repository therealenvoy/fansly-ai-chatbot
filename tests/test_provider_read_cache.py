from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, insert

from src.persistence.schema import CREATORS, metadata
from src.provider_read_cache import ProviderReadCache


def _cache():
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
    return ProviderReadCache(engine, creator_id="creator-1")


def test_provider_read_cache_round_trips_and_upserts_creator_scope():
    cache = _cache()
    now = datetime(2026, 7, 30, 10, tzinfo=timezone.utc)

    cache.put(
        "posting",
        "walls",
        {"walls": [{"id": "wall-1", "name": "Posts"}]},
        fetched_at=now,
        ttl=timedelta(hours=24),
        stale_ttl=timedelta(days=7),
    )
    cache.put(
        "posting",
        "walls",
        {"walls": [{"id": "wall-2", "name": "VIP"}]},
        fetched_at=now + timedelta(minutes=1),
        ttl=timedelta(hours=24),
        stale_ttl=timedelta(days=7),
    )

    snapshot = cache.get("posting", "walls")

    assert snapshot is not None
    assert snapshot.payload == {
        "walls": [{"id": "wall-2", "name": "VIP"}]
    }
    assert snapshot.is_fresh(now + timedelta(hours=23))
    assert snapshot.is_usable_stale(now + timedelta(days=6))
    assert snapshot.age_seconds(now + timedelta(minutes=2)) == 60


def test_provider_read_cache_invalidation_is_namespace_bounded():
    cache = _cache()
    now = datetime(2026, 7, 30, 10, tzinfo=timezone.utc)
    for namespace in ("posting", "analytics"):
        cache.put(
            namespace,
            "snapshot",
            {"namespace": namespace},
            fetched_at=now,
            ttl=timedelta(hours=1),
            stale_ttl=timedelta(hours=2),
        )

    cache.invalidate("posting")

    assert cache.get("posting", "snapshot") is None
    assert cache.get("analytics", "snapshot") is not None
