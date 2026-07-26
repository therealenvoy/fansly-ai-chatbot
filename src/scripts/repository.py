"""Durable creator-owned overrides for conversation scripts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, and_, delete, insert, select, update

from src.persistence.schema import SCRIPT_TEMPLATES, utcnow
from src.scripts.models import ScriptCategory, ScriptTemplate, ScriptVariable


@dataclass(frozen=True)
class StoredScript:
    id: int
    creator_id: str
    template: ScriptTemplate
    is_active: bool
    created_at: datetime
    updated_at: datetime

    def as_json(self) -> dict:
        return {
            "id": self.id,
            "creator_id": self.creator_id,
            "name": self.template.name,
            "category": self.template.category.value,
            "description": self.template.description,
            "messages": list(self.template.messages),
            "variables": [
                variable.model_dump()
                for variable in self.template.variables
            ],
            "conditions": dict(self.template.conditions),
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class ScriptTemplateRepository:
    def __init__(self, engine: Engine, creator_id: str):
        self.engine = engine
        self.creator_id = creator_id

    def list_scripts(self, *, active_only: bool = False) -> list[StoredScript]:
        statement = (
            select(SCRIPT_TEMPLATES)
            .where(SCRIPT_TEMPLATES.c.creator_id == self.creator_id)
            .order_by(
                SCRIPT_TEMPLATES.c.category,
                SCRIPT_TEMPLATES.c.name,
            )
        )
        if active_only:
            statement = statement.where(
                SCRIPT_TEMPLATES.c.is_active.is_(True)
            )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._row(row) for row in rows]

    def get(self, script_id: int) -> StoredScript | None:
        statement = select(SCRIPT_TEMPLATES).where(
            and_(
                SCRIPT_TEMPLATES.c.creator_id == self.creator_id,
                SCRIPT_TEMPLATES.c.id == script_id,
            )
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return self._row(row) if row else None

    def save(
        self,
        template: ScriptTemplate,
        *,
        script_id: int | None = None,
        is_active: bool = True,
    ) -> StoredScript:
        now = utcnow()
        values = {
            "creator_id": self.creator_id,
            "name": template.name,
            "category": template.category.value,
            "description": template.description,
            "messages": list(template.messages),
            "variables": [
                variable.model_dump()
                for variable in template.variables
            ],
            "conditions": dict(template.conditions),
            "is_active": is_active,
            "updated_at": now,
        }
        with self.engine.begin() as connection:
            existing_id = script_id
            if existing_id is None:
                existing_id = connection.execute(
                    select(SCRIPT_TEMPLATES.c.id).where(
                        and_(
                            SCRIPT_TEMPLATES.c.creator_id
                            == self.creator_id,
                            SCRIPT_TEMPLATES.c.name == template.name,
                        )
                    )
                ).scalar_one_or_none()
            if existing_id is None:
                result = connection.execute(
                    insert(SCRIPT_TEMPLATES).values(
                        **values,
                        created_at=now,
                    )
                )
                existing_id = int(result.inserted_primary_key[0])
            else:
                result = connection.execute(
                    update(SCRIPT_TEMPLATES)
                    .where(
                        and_(
                            SCRIPT_TEMPLATES.c.creator_id
                            == self.creator_id,
                            SCRIPT_TEMPLATES.c.id == existing_id,
                        )
                    )
                    .values(**values)
                )
                if not result.rowcount:
                    raise LookupError("script not found")
        saved = self.get(int(existing_id))
        if saved is None:
            raise RuntimeError("saved script could not be read back")
        return saved

    def delete(self, script_id: int) -> bool:
        with self.engine.begin() as connection:
            result = connection.execute(
                delete(SCRIPT_TEMPLATES).where(
                    and_(
                        SCRIPT_TEMPLATES.c.creator_id == self.creator_id,
                        SCRIPT_TEMPLATES.c.id == script_id,
                    )
                )
            )
        return bool(result.rowcount)

    @staticmethod
    def _row(row) -> StoredScript:
        template = ScriptTemplate(
            name=row["name"],
            category=ScriptCategory(row["category"]),
            description=row["description"] or "",
            messages=list(row["messages"] or []),
            variables=[
                ScriptVariable(**variable)
                for variable in (row["variables"] or [])
            ],
            conditions=dict(row["conditions"] or {}),
        )
        return StoredScript(
            id=int(row["id"]),
            creator_id=row["creator_id"],
            template=template,
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
