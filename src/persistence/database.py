"""Database engine configuration shared by every repository."""

from __future__ import annotations

import os

from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import StaticPool


def normalize_database_url(database_url: str) -> str:
    """Normalize Railway's legacy postgres URL for SQLAlchemy."""
    value = database_url.strip()
    if value.startswith("postgres://"):
        return "postgresql+psycopg2://" + value[len("postgres://"):]
    if value.startswith("postgresql://"):
        return "postgresql+psycopg2://" + value[len("postgresql://"):]
    return value


def _is_production_environment(environment: dict[str, str]) -> bool:
    names = (
        environment.get("APP_ENV", ""),
        environment.get("ENVIRONMENT", ""),
        environment.get("RAILWAY_ENVIRONMENT_NAME", ""),
    )
    return any(name.strip().lower() == "production" for name in names)


def create_database_engine(
    database_url: str,
    *,
    environment: dict[str, str] | None = None,
) -> Engine:
    """Create the process-wide engine.

    SQLite remains available for local tests, but production fails closed unless
    it is configured with PostgreSQL.
    """
    env = environment if environment is not None else os.environ
    normalized = normalize_database_url(database_url)
    if not normalized:
        raise RuntimeError("DATABASE_URL is required")
    if _is_production_environment(env) and normalized.startswith("sqlite:"):
        raise RuntimeError("SQLite is not allowed in production")

    if normalized.startswith("sqlite:"):
        kwargs: dict = {
            "future": True,
            "connect_args": {"check_same_thread": False},
        }
        if normalized in {"sqlite://", "sqlite:///:memory:"}:
            kwargs["poolclass"] = StaticPool
        return create_engine(normalized, **kwargs)

    return create_engine(
        normalized,
        future=True,
        pool_pre_ping=True,
        pool_recycle=300,
    )
