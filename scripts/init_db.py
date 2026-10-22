"""Quick-start database initialization: creates all tables directly from the
SQLAlchemy models via `Base.metadata.create_all`.

Limitations (use Alembic instead for anything beyond local/dev quick start):
- No migration history - cannot express incremental schema changes safely.
- Will not alter existing tables (e.g. add a new column to a table that
  already exists); it only creates tables that are missing.
- Not safe to run repeatedly against a production database as the schema
  evolves. Use `alembic upgrade head` (see alembic/) for production.

Usage:
    python scripts/init_db.py
"""
from __future__ import annotations

import asyncio
import logging

from database.models import Base
from database.session import get_engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("init_db")


async def main() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    logger.info("Database tables created (or already present).")


if __name__ == "__main__":
    asyncio.run(main())
