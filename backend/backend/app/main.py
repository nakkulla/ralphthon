from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Literal
from uuid import UUID

from fastapi import Body, FastAPI, File, Form, Query, UploadFile
from fastapi.responses import FileResponse

from .cache import Cache
from .config import get_settings
from .db import apply_schema, create_pool
from .models import HealthOut, ProfileCreate, ProfileUpdate, TagUpdate
from .repository import Repository


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.image_data_dir.mkdir(parents=True, exist_ok=True)
    pool = await create_pool(settings)
    await apply_schema(pool)
    cache = Cache(settings.valkey_url)
    await cache.connect()
    app.state.settings = settings
    app.state.pool = pool
    app.state.cache = cache
    app.state.repo = Repository(pool, cache, settings)
    try:
        yield
    finally:
        await cache.close()
        await pool.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Project Profile Gallery", lifespan=lifespan)

    @app.get("/healthz", response_model=HealthOut)
    async def healthz():
        repo: Repository = app.state.repo
        db_ok = await repo.health_db()
        cache_ok = await app.state.cache.ping()
        status = "ok" if db_ok and cache_ok else "degraded"
        return {"status": status, "db": "ok" if db_ok else "error", "cache": "ok" if cache_ok else "error"}

    @app.post("/profiles")
    async def create_profile(profile: ProfileCreate):
        return await app.state.repo.create_profile(profile)

    @app.get("/profiles")
    async def list_profiles():
        return await app.state.repo.list_profiles()

    @app.get("/profiles/{profile_id}")
    async def get_profile(profile_id: UUID):
        return await app.state.repo.get_profile(profile_id)

    @app.patch("/profiles/{profile_id}")
    async def update_profile(profile_id: UUID, profile: ProfileUpdate):
        return await app.state.repo.update_profile(profile_id, profile, profile.model_fields_set)

    @app.delete("/profiles/{profile_id}")
    async def delete_profile(profile_id: UUID):
        return await app.state.repo.delete_profile(profile_id)

    @app.post("/profiles/{profile_id}/images")
    async def add_image(
        profile_id: UUID,
        file: UploadFile = File(...),
        prompt: str | None = Form(None),
        request_id: str | None = Form(None),
    ):
        return await app.state.repo.add_image(profile_id, file, prompt, request_id)

    @app.get("/profiles/{profile_id}/images")
    async def list_images(profile_id: UUID):
        return await app.state.repo.list_images(profile_id)

    @app.get("/images/{image_id}")
    async def get_image(image_id: UUID):
        path, mime_type = await app.state.repo.get_image_file(image_id)
        return FileResponse(path, media_type=mime_type)

    @app.delete("/images/{image_id}")
    async def delete_image(image_id: UUID):
        return await app.state.repo.delete_image(image_id)

    @app.post("/profiles/{profile_id}/tags")
    async def add_tags(profile_id: UUID, update: TagUpdate):
        return await app.state.repo.add_tags(profile_id, update)

    @app.delete("/profiles/{profile_id}/tags")
    async def remove_tags(profile_id: UUID, update: TagUpdate = Body(...)):
        return await app.state.repo.remove_tags(profile_id, update)

    @app.get("/tags")
    async def list_tags():
        return await app.state.repo.list_tags()

    @app.get("/search")
    async def search(
        q: str | None = None,
        tags: str | None = None,
        match: Literal["any", "all"] = "any",
        kind: Literal["tag", "keyword", "all"] = "all",
        tech: str | None = None,
        tech_match: Literal["any", "all"] = "any",
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        return await app.state.repo.search(q, tags, match, kind, tech, tech_match, limit, offset)

    @app.get("/imggen/{request_id}")
    async def imggen(request_id: str):
        return await app.state.repo.get_imggen(request_id)

    return app


app = create_app()
