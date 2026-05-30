import os

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio

if not (os.getenv("TEST_DATABASE_URL") and os.getenv("TEST_VALKEY_URL")):
    pytest.skip("requires TEST_DATABASE_URL and TEST_VALKEY_URL", allow_module_level=True)


async def test_profile_lifecycle_search_cache_imggen_and_image_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("VALKEY_URL", os.environ["TEST_VALKEY_URL"])
    monkeypatch.setenv("IMAGE_DATA_DIR", str(tmp_path / "images"))
    from backend.app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        # Per-test cleanup for persistent local TEST_DATABASE_URL.
        async with app.state.pool.acquire() as conn:
            await conn.execute("TRUNCATE profile_tags, images, tags, profiles RESTART IDENTITY CASCADE")
        await app.state.cache.delete_pattern("profile:*")
        await app.state.cache.delete_pattern("search:*")
        await app.state.cache.delete_pattern("imggen:*")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            health = await client.get("/healthz")
            assert health.status_code == 200

            created = await client.post("/profiles", json={
                "name": "MoodBoard",
                "summary": "음악 감정 분석 기반 플레이리스트 큐레이션",
                "raw_text": "FastAPI pgvector music ai",
                "tech_stack": ["FastAPI", " pgvector "],
                "domain": "music-ai",
                "tags": ["music", "ai"],
                "keywords": ["감정분석"],
            })
            assert created.status_code == 200
            body = created.json()
            profile_id = body["id"]
            request_id = body["request_id"]
            assert (await client.get(f"/imggen/{request_id}")).json()["status"] == "pending"
            first_get = await client.get(f"/profiles/{profile_id}")
            assert first_get.status_code == 200
            assert first_get.json()["tech_stack"] == ["fastapi", "pgvector"]

            png = b"\x89PNG\r\n\x1a\n" + b"0" * 16
            uploaded = await client.post(
                f"/profiles/{profile_id}/images",
                data={"prompt": "album art", "request_id": request_id},
                files={"file": ("mood.png", png, "image/png")},
            )
            assert uploaded.status_code == 200
            image_id = uploaded.json()["image_id"]
            image_path = tmp_path / "images" / f"{image_id}.png"
            assert image_path.exists()
            assert (await client.get(f"/imggen/{request_id}")).json()["status"] == "stored"
            assert (await client.get(f"/images/{image_id}")).status_code == 200
            image_list = await client.get(f"/profiles/{profile_id}/images")
            assert image_list.status_code == 200
            assert image_list.json()[0]["image_id"] == image_id

            bad_mime = await client.post(
                f"/profiles/{profile_id}/images",
                data={"prompt": "bad"},
                files={"file": ("bad.txt", b"not-image", "text/plain")},
            )
            assert bad_mime.status_code == 422
            too_big = await client.post(
                f"/profiles/{profile_id}/images",
                data={"prompt": "huge"},
                files={"file": ("huge.png", b"\x89PNG\r\n\x1a\n" + b"0" * (5 * 1024 * 1024 + 1), "image/png")},
            )
            assert too_big.status_code == 413

            tags = await client.get("/tags")
            assert tags.status_code == 200
            assert any(item["name"] == "music" for item in tags.json())

            same_params = {"q": "music ai", "tags": "music", "tech": "FASTAPI,pgvector", "tech_match": "all"}
            search = await client.get("/search", params=same_params)
            assert search.status_code == 200
            assert search.json()["items"][0]["id"] == profile_id
            assert search.json()["items"][0]["summary"] == "음악 감정 분석 기반 플레이리스트 큐레이션"
            assert len(search.json()["items"][0]["images"]) == 1

            # Tag writes must invalidate cached profile and exact same search key.
            missing_tag = await client.post("/profiles/00000000-0000-0000-0000-000000000000/tags", json={"tags": ["ghost"]})
            assert missing_tag.status_code == 404
            added_tag = await client.post(f"/profiles/{profile_id}/tags", json={"tags": ["recsys"], "keywords": ["waveform"]})
            assert added_tag.status_code == 200
            tag_search = await client.get("/search", params=same_params)
            assert "recsys" in tag_search.json()["items"][0]["tags"]
            assert "waveform" in tag_search.json()["items"][0]["keywords"]
            tag_profile = await client.get(f"/profiles/{profile_id}")
            assert "recsys" in tag_profile.json()["tags"]
            removed_tag = await client.request("DELETE", f"/profiles/{profile_id}/tags", json={"tags": ["recsys"]})
            assert removed_tag.status_code == 200
            tag_search2 = await client.get("/search", params=same_params)
            assert "recsys" not in tag_search2.json()["items"][0]["tags"]

            # Image writes/deletes must invalidate cached profile and exact same search key.
            uploaded2 = await client.post(
                f"/profiles/{profile_id}/images",
                data={"prompt": "second"},
                files={"file": ("second.png", png, "image/png")},
            )
            image2_id = uploaded2.json()["image_id"]
            image_search = await client.get("/search", params=same_params)
            assert len(image_search.json()["items"][0]["images"]) == 2
            deleted_image = await client.delete(f"/images/{image2_id}")
            assert deleted_image.status_code == 200
            assert (await client.get(f"/images/{image2_id}")).status_code == 404
            image_search2 = await client.get("/search", params=same_params)
            assert len(image_search2.json()["items"][0]["images"]) == 1

            updated = await client.patch(f"/profiles/{profile_id}", json={"summary": "music ai updated summary"})
            assert updated.status_code == 200
            get_after_update = await client.get(f"/profiles/{profile_id}")
            assert get_after_update.json()["summary"] == "music ai updated summary"
            # Same exact query as before update: proves search:* invalidation, not a new cache key.
            search2 = await client.get("/search", params=same_params)
            assert search2.json()["items"][0]["summary"] == "music ai updated summary"

            listed = await client.get("/profiles")
            assert listed.status_code == 200
            assert any(item["id"] == profile_id for item in listed.json())

            deleted = await client.delete(f"/profiles/{profile_id}")
            assert deleted.status_code == 200
            assert not image_path.exists()
            assert (await client.get(f"/images/{image_id}")).status_code == 404
            # Same exact query as before delete: proves cached search result was invalidated.
            assert (await client.get("/search", params=same_params)).json()["items"] == []
