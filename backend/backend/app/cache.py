from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis


class Cache:
    def __init__(self, url: str):
        self.url = url
        self.client: Redis | None = None

    async def connect(self) -> None:
        self.client = Redis.from_url(self.url, decode_responses=True)

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()

    async def ping(self) -> bool:
        if self.client is None:
            return False
        try:
            return bool(await self.client.ping())
        except Exception:
            return False

    async def get_json(self, key: str) -> Any | None:
        if self.client is None:
            return None
        try:
            value = await self.client.get(key)
            if value is None:
                return None
            return json.loads(value)
        except Exception:
            return None

    async def set_json(self, key: str, value: Any, ttl: int) -> None:
        if self.client is None:
            return
        try:
            await self.client.set(key, json.dumps(value, ensure_ascii=False, default=str), ex=ttl)
        except Exception:
            return

    async def delete(self, key: str) -> None:
        if self.client is None:
            return
        try:
            await self.client.delete(key)
        except Exception:
            return

    async def delete_pattern(self, pattern: str) -> None:
        if self.client is None:
            return
        try:
            keys = [key async for key in self.client.scan_iter(match=pattern, count=100)]
            if keys:
                await self.client.delete(*keys)
        except Exception:
            return
