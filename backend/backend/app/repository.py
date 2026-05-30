from __future__ import annotations

import hashlib
import json
import mimetypes
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import asyncpg
from fastapi import HTTPException, UploadFile

from .cache import Cache
from .config import Settings
from .models import ProfileCreate, ProfileUpdate, TagUpdate, normalize_csv

ALLOWED_IMAGE_MIME = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


class Repository:
    def __init__(self, pool: asyncpg.Pool, cache: Cache, settings: Settings):
        self.pool = pool
        self.cache = cache
        self.settings = settings

    async def health_db(self) -> bool:
        try:
            async with self.pool.acquire() as conn:
                return await conn.fetchval("SELECT 1") == 1
        except Exception:
            return False

    async def _invalidate_profile(self, profile_id: UUID | str) -> None:
        await self.cache.delete(f"profile:{profile_id}")
        await self.cache.delete_pattern("search:*")

    async def _invalidate_search(self) -> None:
        await self.cache.delete_pattern("search:*")

    async def _upsert_tags(self, conn: asyncpg.Connection, profile_id: UUID | str, names: list[str], kind: str) -> None:
        for name in names:
            tag_id = await conn.fetchval(
                """
                INSERT INTO tags(name, kind) VALUES($1, $2)
                ON CONFLICT (name, kind) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
                """,
                name,
                kind,
            )
            await conn.execute(
                "INSERT INTO profile_tags(profile_id, tag_id) VALUES($1, $2) ON CONFLICT DO NOTHING",
                profile_id,
                tag_id,
            )

    async def _replace_tags(self, conn: asyncpg.Connection, profile_id: UUID | str, names: list[str], kind: str) -> None:
        await conn.execute(
            """
            DELETE FROM profile_tags pt
            USING tags t
            WHERE pt.tag_id = t.id AND pt.profile_id = $1 AND t.kind = $2
            """,
            profile_id,
            kind,
        )
        await self._upsert_tags(conn, profile_id, names, kind)

    async def _tags_for_profile(self, conn: asyncpg.Connection, profile_id: UUID | str, kind: str) -> list[str]:
        rows = await conn.fetch(
            """
            SELECT t.name
            FROM tags t
            JOIN profile_tags pt ON pt.tag_id = t.id
            WHERE pt.profile_id = $1 AND t.kind = $2
            ORDER BY t.name
            """,
            profile_id,
            kind,
        )
        return [row["name"] for row in rows]

    async def _images_for_profile(self, conn: asyncpg.Connection, profile_id: UUID | str) -> list[dict[str, Any]]:
        rows = await conn.fetch(
            """
            SELECT id, profile_id, url, prompt, mime_type, width, height, created_at
            FROM images
            WHERE profile_id = $1
            ORDER BY created_at
            """,
            profile_id,
        )
        return [self._image_dict(row) for row in rows]

    def _image_dict(self, row: asyncpg.Record) -> dict[str, Any]:
        return {
            "image_id": str(row["id"]),
            "profile_id": str(row["profile_id"]) if "profile_id" in row and row["profile_id"] is not None else None,
            "url": row["url"],
            "prompt": row["prompt"],
            "mime_type": row["mime_type"],
            "width": row["width"],
            "height": row["height"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }

    async def _profile_dict(self, conn: asyncpg.Connection, row: asyncpg.Record) -> dict[str, Any]:
        profile_id = row["id"]
        return {
            "id": str(profile_id),
            "name": row["name"],
            "summary": row["summary"],
            "raw_text": row["raw_text"],
            "tech_stack": list(row["tech_stack"] or []),
            "domain": row["domain"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            "tags": await self._tags_for_profile(conn, profile_id, "tag"),
            "keywords": await self._tags_for_profile(conn, profile_id, "keyword"),
            "images": await self._images_for_profile(conn, profile_id),
        }

    async def create_profile(self, data: ProfileCreate) -> dict[str, Any]:
        request_id = f"req_{uuid4().hex[:12]}"
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    INSERT INTO profiles(name, summary, raw_text, tech_stack, domain)
                    VALUES($1, $2, $3, $4::text[], $5)
                    RETURNING *
                    """,
                    data.name,
                    data.summary,
                    data.raw_text,
                    data.tech_stack,
                    data.domain,
                )
                await self._upsert_tags(conn, row["id"], data.tags, "tag")
                await self._upsert_tags(conn, row["id"], data.keywords, "keyword")
                profile = await self._profile_dict(conn, row)
        await self.cache.set_json(f"imggen:{request_id}", {"request_id": request_id, "status": "pending"}, 600)
        await self._invalidate_search()
        profile.update({"request_id": request_id, "status": "created"})
        return profile

    async def get_profile(self, profile_id: UUID, use_cache: bool = True) -> dict[str, Any]:
        cache_key = f"profile:{profile_id}"
        if use_cache:
            cached = await self.cache.get_json(cache_key)
            if cached is not None:
                return cached
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM profiles WHERE id = $1", profile_id)
            if row is None:
                raise HTTPException(status_code=404, detail="profile not found")
            profile = await self._profile_dict(conn, row)
        if use_cache:
            await self.cache.set_json(cache_key, profile, 300)
        return profile

    async def list_profiles(self) -> list[dict[str, Any]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM profiles ORDER BY updated_at DESC")
            return [await self._profile_dict(conn, row) for row in rows]

    async def update_profile(self, profile_id: UUID, data: ProfileUpdate, fields: set[str]) -> dict[str, Any]:
        values = data.model_dump(exclude_unset=True)
        profile_fields = [field for field in ["name", "summary", "raw_text", "tech_stack", "domain"] if field in fields]
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                if profile_fields:
                    assignments: list[str] = []
                    args: list[Any] = []
                    for index, field in enumerate(profile_fields, start=1):
                        cast = "::text[]" if field == "tech_stack" else ""
                        assignments.append(f"{field} = ${index}{cast}")
                        args.append(values[field])
                    args.append(profile_id)
                    await conn.execute(
                        f"UPDATE profiles SET {', '.join(assignments)}, updated_at = now() WHERE id = ${len(args)}",
                        *args,
                    )
                else:
                    await conn.execute("UPDATE profiles SET updated_at = now() WHERE id = $1", profile_id)
                if "tags" in fields:
                    await self._replace_tags(conn, profile_id, data.tags, "tag")
                if "keywords" in fields:
                    await self._replace_tags(conn, profile_id, data.keywords, "keyword")
                row = await conn.fetchrow("SELECT * FROM profiles WHERE id = $1", profile_id)
                if row is None:
                    raise HTTPException(status_code=404, detail="profile not found")
                profile = await self._profile_dict(conn, row)
        await self._invalidate_profile(profile_id)
        return profile

    async def delete_profile(self, profile_id: UUID) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch("SELECT file_path FROM images WHERE profile_id = $1", profile_id)
                result = await conn.execute("DELETE FROM profiles WHERE id = $1", profile_id)
                if result.endswith("0"):
                    raise HTTPException(status_code=404, detail="profile not found")
        for row in rows:
            Path(row["file_path"]).unlink(missing_ok=True)
        await self._invalidate_profile(profile_id)
        return {"id": str(profile_id), "status": "deleted"}

    async def add_image(self, profile_id: UUID, file: UploadFile, prompt: str | None, request_id: str | None) -> dict[str, Any]:
        if file.content_type not in ALLOWED_IMAGE_MIME:
            raise HTTPException(status_code=422, detail="unsupported image MIME type")
        content = await file.read()
        if len(content) > self.settings.max_image_bytes:
            raise HTTPException(status_code=413, detail="image too large")
        async with self.pool.acquire() as conn:
            exists = await conn.fetchval("SELECT EXISTS(SELECT 1 FROM profiles WHERE id = $1)", profile_id)
            if not exists:
                raise HTTPException(status_code=404, detail="profile not found")
        image_id = uuid4()
        ext = ALLOWED_IMAGE_MIME[file.content_type]
        self.settings.image_data_dir.mkdir(parents=True, exist_ok=True)
        target = self.settings.image_data_dir / f"{image_id}{ext}"
        target.write_bytes(content)
        url = f"/images/{image_id}"
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO images(id, profile_id, file_path, url, prompt, mime_type)
                VALUES($1, $2, $3, $4, $5, $6)
                RETURNING id, profile_id, url, prompt, mime_type, width, height, created_at
                """,
                image_id,
                profile_id,
                str(target),
                url,
                prompt,
                file.content_type,
            )
        if request_id:
            await self.cache.set_json(f"imggen:{request_id}", {"request_id": request_id, "status": "stored"}, 600)
        await self._invalidate_profile(profile_id)
        return self._image_dict(row)

    async def list_images(self, profile_id: UUID) -> list[dict[str, Any]]:
        async with self.pool.acquire() as conn:
            return await self._images_for_profile(conn, profile_id)

    async def get_image_file(self, image_id: UUID) -> tuple[Path, str]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT file_path, mime_type FROM images WHERE id = $1", image_id)
        if row is None:
            raise HTTPException(status_code=404, detail="image not found")
        path = Path(row["file_path"])
        if not path.exists():
            raise HTTPException(status_code=404, detail="image not found")
        return path, row["mime_type"]

    async def delete_image(self, image_id: UUID) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("DELETE FROM images WHERE id = $1 RETURNING profile_id, file_path", image_id)
        if row is None:
            raise HTTPException(status_code=404, detail="image not found")
        Path(row["file_path"]).unlink(missing_ok=True)
        await self._invalidate_profile(row["profile_id"])
        return {"id": str(image_id), "status": "deleted"}

    async def add_tags(self, profile_id: UUID, data: TagUpdate) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await self._upsert_tags(conn, profile_id, data.tags, "tag")
                await self._upsert_tags(conn, profile_id, data.keywords, "keyword")
        await self._invalidate_profile(profile_id)
        return await self.get_profile(profile_id, use_cache=False)

    async def remove_tags(self, profile_id: UUID, data: TagUpdate) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                for kind, names in [("tag", data.tags), ("keyword", data.keywords)]:
                    if names:
                        await conn.execute(
                            """
                            DELETE FROM profile_tags pt
                            USING tags t
                            WHERE pt.tag_id = t.id AND pt.profile_id = $1 AND t.kind = $2 AND t.name = ANY($3::text[])
                            """,
                            profile_id,
                            kind,
                            names,
                        )
        await self._invalidate_profile(profile_id)
        return await self.get_profile(profile_id, use_cache=False)

    async def list_tags(self) -> list[dict[str, str]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT name, kind FROM tags ORDER BY kind, name")
        return [{"name": row["name"], "kind": row["kind"]} for row in rows]

    def _search_cache_key(self, payload: dict[str, Any]) -> str:
        normalized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return "search:" + hashlib.sha256(normalized.encode()).hexdigest()

    async def search(
        self,
        q: str | None,
        tags: str | None,
        match: str,
        kind: str,
        tech: str | None,
        tech_match: str,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        tag_values = normalize_csv(tags)
        tech_values = normalize_csv(tech)
        payload = {
            "q": q or "",
            "tags": tag_values,
            "match": match,
            "kind": kind,
            "tech": tech_values,
            "tech_match": tech_match,
            "limit": limit,
            "offset": offset,
        }
        cache_key = self._search_cache_key(payload)
        cached = await self.cache.get_json(cache_key)
        if cached is not None:
            return cached

        conditions: list[str] = []
        args: list[Any] = []
        rank_expr = "0::real"
        if q:
            args.append(q)
            q_pos = len(args)
            conditions.append(f"p.search_vector @@ websearch_to_tsquery('simple', ${q_pos})")
            rank_expr = f"ts_rank(p.search_vector, websearch_to_tsquery('simple', ${q_pos}))"
        if tag_values:
            args.append(tag_values)
            tags_pos = len(args)
            args.append(kind)
            kind_pos = len(args)
            kind_condition = f"(${kind_pos} = 'all' OR t.kind = ${kind_pos})"
            if match == "all":
                conditions.append(
                    f"""p.id IN (
                        SELECT pt.profile_id
                        FROM profile_tags pt JOIN tags t ON t.id = pt.tag_id
                        WHERE t.name = ANY(${tags_pos}::text[]) AND {kind_condition}
                        GROUP BY pt.profile_id
                        HAVING count(DISTINCT t.name) = {len(tag_values)}
                    )"""
                )
            else:
                conditions.append(
                    f"""p.id IN (
                        SELECT pt.profile_id
                        FROM profile_tags pt JOIN tags t ON t.id = pt.tag_id
                        WHERE t.name = ANY(${tags_pos}::text[]) AND {kind_condition}
                    )"""
                )
        if tech_values:
            args.append(tech_values)
            tech_pos = len(args)
            op = "@>" if tech_match == "all" else "&&"
            conditions.append(f"p.tech_stack {op} ${tech_pos}::text[]")
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        args.extend([limit, offset])
        limit_pos = len(args) - 1
        offset_pos = len(args)
        order = "rank DESC, p.updated_at DESC" if q else "p.updated_at DESC"
        sql = f"""
            SELECT p.*, {rank_expr} AS rank
            FROM profiles p
            {where}
            ORDER BY {order}
            LIMIT ${limit_pos} OFFSET ${offset_pos}
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
            items = [await self._profile_dict(conn, row) for row in rows]
        result = {"items": items, "limit": limit, "offset": offset}
        await self.cache.set_json(cache_key, result, 60)
        return result

    async def get_imggen(self, request_id: str) -> dict[str, str]:
        value = await self.cache.get_json(f"imggen:{request_id}")
        if value is None:
            raise HTTPException(status_code=404, detail="request not found")
        return value
