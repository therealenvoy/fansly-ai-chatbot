"""Durable registry for provider-ready media used by scripts and flows."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy import Engine, and_, delete, insert, select, update

from src.persistence.schema import MEDIA_ASSETS, utcnow


@dataclass(frozen=True)
class MediaAsset:
    id: int | None
    creator_id: str
    provider_media_id: str
    title: str
    account_media_id: str | None = None
    file_name: str | None = None
    media_type: str = "video"
    mime_type: str | None = None
    thumbnail_url: str | None = None
    preview_url: str | None = None
    duration_ms: int | None = None
    width: int | None = None
    height: int | None = None
    tags: tuple[str, ...] = ()
    source: str = "manual"
    status: str = "ready"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def as_json(self) -> dict:
        value = asdict(self)
        value["tags"] = list(self.tags)
        value["created_at"] = (
            self.created_at.isoformat() if self.created_at else None
        )
        value["updated_at"] = (
            self.updated_at.isoformat() if self.updated_at else None
        )
        return value


class MediaAssetRepository:
    def __init__(self, engine: Engine, creator_id: str):
        self.engine = engine
        self.creator_id = creator_id

    def list_assets(
        self,
        *,
        query: str = "",
        media_type: str = "",
    ) -> list[MediaAsset]:
        statement = (
            select(MEDIA_ASSETS)
            .where(MEDIA_ASSETS.c.creator_id == self.creator_id)
            .order_by(
                MEDIA_ASSETS.c.updated_at.desc(),
                MEDIA_ASSETS.c.id.desc(),
            )
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        assets = [self._row(row) for row in rows]
        normalized_query = query.strip().lower()
        normalized_type = media_type.strip().lower()
        if normalized_query:
            assets = [
                asset
                for asset in assets
                if normalized_query
                in " ".join(
                    (
                        asset.title,
                        asset.file_name or "",
                        asset.provider_media_id,
                        " ".join(asset.tags),
                    )
                ).lower()
            ]
        if normalized_type:
            assets = [
                asset
                for asset in assets
                if asset.media_type == normalized_type
            ]
        return assets

    def get(self, asset_id: int) -> MediaAsset | None:
        statement = select(MEDIA_ASSETS).where(
            and_(
                MEDIA_ASSETS.c.creator_id == self.creator_id,
                MEDIA_ASSETS.c.id == asset_id,
            )
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return self._row(row) if row else None

    def save(self, asset: MediaAsset) -> MediaAsset:
        now = utcnow()
        values = {
            "creator_id": self.creator_id,
            "provider_media_id": asset.provider_media_id,
            "account_media_id": asset.account_media_id,
            "title": asset.title,
            "file_name": asset.file_name,
            "media_type": asset.media_type,
            "mime_type": asset.mime_type,
            "thumbnail_url": asset.thumbnail_url,
            "preview_url": asset.preview_url,
            "duration_ms": asset.duration_ms,
            "width": asset.width,
            "height": asset.height,
            "tags": list(asset.tags),
            "source": asset.source,
            "status": asset.status,
            "updated_at": now,
        }
        with self.engine.begin() as connection:
            existing_id = asset.id
            if existing_id is None:
                existing_id = connection.execute(
                    select(MEDIA_ASSETS.c.id).where(
                        and_(
                            MEDIA_ASSETS.c.creator_id == self.creator_id,
                            MEDIA_ASSETS.c.provider_media_id
                            == asset.provider_media_id,
                        )
                    )
                ).scalar_one_or_none()
            if existing_id is None:
                result = connection.execute(
                    insert(MEDIA_ASSETS).values(
                        **values,
                        created_at=now,
                    )
                )
                existing_id = int(result.inserted_primary_key[0])
            else:
                connection.execute(
                    update(MEDIA_ASSETS)
                    .where(
                        and_(
                            MEDIA_ASSETS.c.creator_id == self.creator_id,
                            MEDIA_ASSETS.c.id == existing_id,
                        )
                    )
                    .values(**values)
                )
        saved = self.get(int(existing_id))
        if saved is None:
            raise RuntimeError("saved media asset could not be read back")
        return saved

    def delete(self, asset_id: int) -> bool:
        with self.engine.begin() as connection:
            result = connection.execute(
                delete(MEDIA_ASSETS).where(
                    and_(
                        MEDIA_ASSETS.c.creator_id == self.creator_id,
                        MEDIA_ASSETS.c.id == asset_id,
                    )
                )
            )
        return bool(result.rowcount)

    @staticmethod
    def _row(row) -> MediaAsset:
        return MediaAsset(
            id=int(row["id"]),
            creator_id=row["creator_id"],
            provider_media_id=row["provider_media_id"],
            account_media_id=row["account_media_id"],
            title=row["title"],
            file_name=row["file_name"],
            media_type=row["media_type"],
            mime_type=row["mime_type"],
            thumbnail_url=row["thumbnail_url"],
            preview_url=row["preview_url"],
            duration_ms=row["duration_ms"],
            width=row["width"],
            height=row["height"],
            tags=tuple(row["tags"] or []),
            source=row["source"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
