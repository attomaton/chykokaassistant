"""Async SQLAlchemy engine/session setup.

Uses NullPool because serverless functions should not hold long-lived
connection pools across invocations; pair this with a Postgres provider
that offers server-side connection pooling (Neon, Supabase, RDS Proxy)
so many short-lived serverless connections do not exhaust Postgres.
"""
from __future__ import annotations

from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from config import get_settings


def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    if url.startswith("postgresql+asyncpg://"):
        # asyncpg's connect() has no "sslmode" kwarg (that's a libpq/psycopg2
        # concept); translate the common "sslmode=require"-style URLs many
        # Postgres providers hand out into the "ssl=true" form asyncpg
        # understands, so the same DATABASE_URL works for both driver styles.
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        sslmode = query.pop("sslmode", None)
        if sslmode and "ssl" not in query:
            # asyncpg's `ssl` kwarg accepts the same disable/allow/prefer/
            # require/verify-ca/verify-full values as libpq's sslmode, just
            # under a different parameter name.
            query["ssl"] = sslmode.lower()
        url = urlunsplit(parts._replace(query=urlencode(query)))

    return url


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    url = normalize_database_url(settings.database_url)
    connect_args = {}
    if url.startswith("sqlite"):
        # Tests use sqlite+aiosqlite; NullPool is incompatible with in-memory
        # sqlite across connections, so tests build their own engine instead
        # of relying on this singleton.
        return create_async_engine(url, connect_args={"check_same_thread": False})
    return create_async_engine(url, poolclass=NullPool, pool_pre_ping=True, connect_args=connect_args)


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)
