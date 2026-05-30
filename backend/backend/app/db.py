from __future__ import annotations

from pathlib import Path

import asyncpg

from .config import Settings


async def create_pool(settings: Settings) -> asyncpg.Pool:
    return await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5)


async def apply_schema(pool: asyncpg.Pool) -> None:
    schema_path = Path(__file__).resolve().parents[2] / "schema.sql"
    schema = schema_path.read_text()
    async with pool.acquire() as conn:
        await conn.execute(schema)
