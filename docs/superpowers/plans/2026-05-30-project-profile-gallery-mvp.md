# Project Profile Gallery MVP Implementation Plan

> **For agentic workers:** REQUIRED EXECUTION SKILL: use the workflow-selected execution skill to implement this plan task-by-task. For Beads-backed work, use `superpowers:executing-plans` by default; use `superpowers:subagent-driven-development` only when the parent Bead has `metadata.execution_mode=subagent_driven` or the user explicitly requested subagent implementation. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Project Profile Gallery MVP so storyboard Scenes 0–7 work end-to-end.

**Architecture:** FastAPI owns persistence/search/static image serving; `pgal` Typer CLI is a thin HTTP client; `skills/profile-gallery` documents the Codex orchestration path that gathers repo/Codex context, calls `image_gen`, then calls `pgal`. PostgreSQL stores canonical profile data and FTS; Valkey caches profile/search/imggen state and is best-effort.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, redis.asyncio, Typer, httpx, pytest, Docker Compose, PostgreSQL 16, Valkey 8.

**Spec:** `docs/superpowers/specs/2026-05-30-project-profile-gallery-design.md`
**Storyboard:** `docs/superpowers/specs/2026-05-30-project-profile-gallery-storyboard.md`
**Parent Bead:** `ralphthon-bje`
**Topology:** `current_same_direct`.

---

## File Structure

- Create `docker-compose.yml`: starts `postgres`, `valkey`, `backend`; mounts image data volume and exposes backend on `8000`.
- Create `backend/pyproject.toml`: backend dependencies and pytest config.
- Create `backend/Dockerfile`: install backend package and run uvicorn.
- Create `backend/schema.sql`: idempotent PostgreSQL schema with pgcrypto, profiles/images/tags/profile_tags, generated FTS vector, GIN indexes.
- Create `backend/backend/__init__.py` and `backend/backend/app/__init__.py`: package markers.
- Create `backend/backend/app/config.py`: env-driven settings.
- Create `backend/backend/app/db.py`: asyncpg pool creation, schema application, query helpers.
- Create `backend/backend/app/cache.py`: Valkey client wrapper with best-effort get/set/delete/scan-delete.
- Create `backend/backend/app/models.py`: Pydantic request/response models and normalization helpers.
- Create `backend/backend/app/repository.py`: DB logic for profile CRUD, tags, images, search, cache invalidation.
- Create `backend/backend/app/main.py`: FastAPI app, startup/shutdown, routes. Import path is always `backend.app...`.
- Create `backend/tests/test_models.py`: pure normalization/model tests.
- Create `backend/tests/test_api.py`: integration tests using real PostgreSQL/Valkey URLs from env; skipped if missing.
- Create `cli/pyproject.toml`: CLI dependencies and pytest config.
- Create `cli/pgal/__init__.py`, `cli/pgal/client.py`, `cli/pgal/main.py`: Typer commands and HTTP client.
- Create `cli/tests/test_cli.py`: Typer CliRunner tests with monkeypatched HTTP client.
- Create `skills/profile-gallery/SKILL.md`: single integrated skill workflow.
- Create `skills/profile-gallery/references/cli-commands.md`: CLI command reference.
- Create `skills/profile-gallery/references/image-prompting.md`: image prompt guide.
- Create `scripts/storyboard_e2e.py`: docker/CLI e2e helper for Scenes 0, 4, 5, 5b, 6, 7 using a tiny generated PNG fixture.
- Create `scripts/skill_flow_check.py`: static/dry-run verifier for Scenes 1–3 and Acceptance 6 ordering: auto collect → draft → user confirmation → image_gen → keyword enrichment → `pgal profile create` → `pgal image add --request-id` → `pgal search`.
- Modify `README.md`: quickstart commands and storyboard verification command.

---

### Task 1: Backend model contracts and schema skeleton

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/backend/__init__.py`
- Create: `backend/backend/app/__init__.py`
- Create: `backend/backend/app/models.py`
- Create: `backend/schema.sql`
- Test: `backend/tests/test_models.py`

- [ ] **Step 1: Write failing model tests**

Create `backend/tests/test_models.py`:

```python
from backend.app.models import ProfileCreate, normalize_csv, normalize_tech_stack


def test_normalize_tech_stack_lowercases_trims_and_dedupes():
    assert normalize_tech_stack([" FastAPI ", "fastapi", "PGVector", ""]) == ["fastapi", "pgvector"]


def test_normalize_csv_splits_trims_and_dedupes():
    assert normalize_csv(" music, ai, music ,, web ") == ["music", "ai", "web"]


def test_profile_create_normalizes_tech_stack():
    model = ProfileCreate(name="MoodBoard", tech_stack=[" Next.js ", "FASTAPI"])
    assert model.tech_stack == ["next.js", "fastapi"]
```

- [ ] **Step 2: Run RED**

Run:

```bash
uv run --project backend pytest backend/tests/test_models.py -q
```

Expected: FAIL because `backend/pyproject.toml` or `backend.app.models` does not exist.

- [ ] **Step 3: Implement minimal model/schema files**

Create `backend/pyproject.toml` with package metadata and dependencies: `fastapi`, `uvicorn[standard]`, `asyncpg`, `redis`, `python-multipart`, `pydantic`, and dev dependency `pytest`, `pytest-asyncio`, `httpx`.

Create `backend/backend/app/models.py` with:
- `normalize_list(values: Iterable[str]) -> list[str]`
- `normalize_tech_stack(values: Iterable[str]) -> list[str]`
- `normalize_csv(value: str | None) -> list[str]`
- Pydantic models: `ProfileCreate`, `ProfileUpdate`, `ProfileOut`, `ImageOut`, `SearchResponse`, `TagUpdate`, `ImgGenStatus`, `HealthOut`.
- Validators that normalize `tech_stack`, `tags`, and `keywords`.

Create `backend/schema.sql` with idempotent DDL:
- `CREATE EXTENSION IF NOT EXISTS pgcrypto;`
- `profiles` with `search_vector generated always as (...) stored`.
- `images`, `tags`, `profile_tags`.
- GIN indexes on `search_vector`, `tech_stack`, unique `tags(name,kind)`, and `profile_tags(tag_id)`.

- [ ] **Step 4: Run GREEN**

Run:

```bash
uv run --project backend pytest backend/tests/test_models.py -q
```

Expected: PASS.

---

### Task 2: Backend API CRUD/search/cache/image behavior

**Files:**
- Create: `backend/backend/app/config.py`
- Create: `backend/backend/app/db.py`
- Create: `backend/backend/app/cache.py`
- Create: `backend/backend/app/repository.py`
- Create: `backend/backend/app/main.py`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write failing API integration tests**

Create `backend/tests/test_api.py` with tests that require `TEST_DATABASE_URL` and `TEST_VALKEY_URL` and skip otherwise. Tests must:

```python
import os
import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio

pytest.skip("requires TEST_DATABASE_URL and TEST_VALKEY_URL", allow_module_level=True) if not (os.getenv("TEST_DATABASE_URL") and os.getenv("TEST_VALKEY_URL")) else None

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
            assert (await client.get(f"/images/{image_id}")).status_code == 404
            # Same exact query as before delete: proves cached search result was invalidated.
            assert (await client.get("/search", params=same_params)).json()["items"] == []
```

- [ ] **Step 2: Run RED**

Run with local services:

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/profile_gallery_test TEST_VALKEY_URL=redis://localhost:6379/1 uv run --project backend pytest backend/tests/test_api.py -q
```

Expected: FAIL because backend API modules are not implemented. The test includes per-run cleanup via `TRUNCATE ... CASCADE` plus cache pattern deletion so persistent local test DB state does not leak between runs.

- [ ] **Step 3: Implement backend app**

Implement:
- startup creates asyncpg pool, applies `schema.sql`, creates image dir.
- cache wrapper methods: `get_json`, `set_json`, `delete`, `delete_pattern` using `SCAN` for `search:*`.
- repository methods: create/get/list/update/delete profile, add/list/delete image, add/remove tags, list tags, search, get imggen.
- `create_profile` returns `id`, `request_id`, `status=created`; stores `imggen:{request_id}=pending`.
- `add_image` validates MIME type is `image/png`, `image/jpeg`, or `image/webp`, rejects other MIME values with 422, rejects files larger than `MAX_IMAGE_BYTES` (default 5 MiB) with 413, writes file under `IMAGE_DATA_DIR/{image_id}{ext}`, inserts row, updates `imggen:{request_id}=stored` when provided, invalidates profile/search caches.
- `delete_profile` removes DB row and unlinks all profile image files after selecting their paths; `/images/{id}` returns 404 after delete. `delete_image` removes a single row and file and invalidates `profile:{id}` plus `search:*`. Tag add/remove also invalidate `profile:{id}` plus `search:*`. `profile list`, `image list/delete`, tag add/remove, and `GET /tags` have minimum integration coverage.
- `search` uses `websearch_to_tsquery('simple', q)` when `q` is set, tag filters, kind filters, tech array `&&`/`@>` on canonical arrays, returns profiles with images/tags/keywords.
- all cache operations are best-effort; DB remains authoritative.

- [ ] **Step 4: Run GREEN**

Run:

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/profile_gallery_test TEST_VALKEY_URL=redis://localhost:6379/1 uv run --project backend pytest backend/tests/test_api.py -q
```

Expected: PASS when postgres/valkey services are available.

---

### Task 3: Docker Compose backend runtime

**Files:**
- Create: `backend/Dockerfile`
- Create: `docker-compose.yml`
- Modify: `README.md`

- [ ] **Step 1: Write runtime smoke command**

The verification command for this task is:

```bash
docker compose up -d --build
python3 - <<'PY'
import json, urllib.request
print(json.load(urllib.request.urlopen('http://localhost:8000/healthz', timeout=10)))
PY
```

Expected before implementation: FAIL because compose/backend runtime is missing.

- [ ] **Step 2: Implement Dockerfile and compose**

Create:
- `backend/Dockerfile` based on `python:3.12-slim`, installs backend package with pip, runs `uvicorn backend.app.main:create_app --factory --host 0.0.0.0 --port 8000`. The image installs `backend/` as a package so `backend.app` imports resolve.
- `docker-compose.yml` with `postgres` (`pgvector/pgvector:pg16`), `valkey` (`valkey/valkey:8`), `backend`, volumes `pgdata`, `imgdata`, healthchecks, env `DATABASE_URL`, `VALKEY_URL`, `IMAGE_DATA_DIR=/data/images`.
- `README.md` quickstart: `docker compose up -d --build`, `curl localhost:8000/healthz`, `PGAL_API_URL=http://localhost:8000`.

- [ ] **Step 3: Run GREEN smoke**

Run the smoke command. Expected JSON: `{"status":"ok","db":"ok","cache":"ok"}`.

---

### Task 4: CLI command surface

**Files:**
- Create: `cli/pyproject.toml`
- Create: `cli/pgal/__init__.py`
- Create: `cli/pgal/client.py`
- Create: `cli/pgal/main.py`
- Test: `cli/tests/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Create `cli/tests/test_cli.py` using Typer `CliRunner` and monkeypatch `pgal.main.ApiClient` fake methods. Cover:
- `profile create --data - --json` posts JSON and prints id/request_id.
- `profile get <id> --json` prints profile JSON.
- `profile list --json` prints list JSON.
- `profile update <id> --data - --json` prints updated status.
- `profile delete <id> --json` prints deleted status.
- `image add <id> --file path --prompt text --request-id req --json` passes request id.
- `image list <id> --json` and `image delete <image_id> --json` call matching endpoints.
- `tag add`, `tag remove`, and `tag list --json` call matching endpoints.
- `search --q ... --tags ... --tech ... --tech-match all --json` passes query params.
- backend error raises non-zero exit and JSON error in `--json` mode.

- [ ] **Step 2: Run RED**

Run:

```bash
uv run --project cli pytest cli/tests/test_cli.py -q
```

Expected: FAIL because CLI package does not exist.

- [ ] **Step 3: Implement CLI**

Implement Typer app:
- env/default API URL: `PGAL_API_URL` or `http://localhost:8000`, optional `--api-url`.
- groups: `profile`, `image`, `tag`, root `search`.
- `cli/pyproject.toml` includes `[project.scripts] pgal = "pgal.main:app"` so `uv run --project cli pgal ...` works.
- JSON output uses `--json`, matching the spec/storyboard. JSON input uses `--data <file|->` so `--json` is never ambiguous.
- Human output prints compact tables; `--json` output prints backend JSON.
- HTTP errors produce non-zero exit and JSON error when `--json`.

- [ ] **Step 4: Run GREEN**

Run:

```bash
uv run --project cli pytest cli/tests/test_cli.py -q
uv run --project cli pgal --help
```

Expected: tests PASS and help exits 0.

---

### Task 5: Profile Gallery Codex skill

**Files:**
- Create: `skills/profile-gallery/SKILL.md`
- Create: `skills/profile-gallery/references/cli-commands.md`
- Create: `skills/profile-gallery/references/image-prompting.md`

> **Required sub-skill:** Use `skill-creator` for SKILL.md draft, eval prompts, and iteration cycles in this task.

- [ ] **Step 1: Write skill contract checklist**

Before writing the skill, verify the skill must include:
- trigger description: project profile register/update/search/delete and representative image generation.
- registration flow: auto collect repo + Codex memory/context; user-provided text/file has priority; present draft; require user confirmation before `image_gen` and `pgal` writes.
- image flow: build prompt, call `image_gen`, add image-derived keywords, call `pgal profile create`, then `pgal image add --request-id`.
- search flow: map tech stack search to `pgal search --tech`.
- update/delete flows via CLI.
- no automatic install into live `~/.codex/skills`.

- [ ] **Step 2: Implement skill docs**

Create SKILL.md and references with the checklist above and exact CLI commands.

- [ ] **Step 3: Verify skill docs**

Run:

```bash
rg -n "image_gen|request-id|사용자 컨펌|--tech|~/.codex/skills" skills/profile-gallery
python3 scripts/skill_flow_check.py
```

Expected: all required phrases are present, install is guidance-only, and `skill_flow_check.py` confirms the documented registration order is auto collection → draft → user confirmation → `image_gen` → keyword enrichment → `pgal profile create --data ... --json` → `pgal image add --request-id` → `pgal search --json`.

---

### Task 6: Storyboard e2e verifier

**Files:**
- Create: `scripts/storyboard_e2e.py`
- Create: `scripts/skill_flow_check.py`
- Modify: `README.md`

- [ ] **Step 1: Write failing e2e script skeleton**

Create `scripts/storyboard_e2e.py` that exits non-zero until all scenes pass. It should:
- read `PGAL_BIN` or default `uv run --project cli pgal`.
- use `PGAL_API_URL` default `http://localhost:8000`.
- call `/healthz`.
- create a profile via CLI JSON stdin with `pgal profile create --data - --json`.
- run `pgal profile get <id> --json` and confirm canonical tech stack.
- write a tiny PNG fixture under `.tmp/storyboard/moodboard.png`.
- upload image with `--request-id`.
- run `pgal search --q`, `pgal search --tech ... --tech-match all --json`.
- run the exact same search before and after update to verify immediate `search:*` invalidation.
- update summary.
- delete profile, then run the exact same search again to verify delete invalidation.
- verify `/images/{id}` returns 404.

- [ ] **Step 2: Run RED**

Run:

```bash
python3 scripts/storyboard_e2e.py
```

Expected: FAIL before backend/CLI is fully wired or before services are up.

- [ ] **Step 3: Complete script and README**

Make the script print scene names and assert expected JSON fields. Add README section:

```bash
docker compose up -d --build
PGAL_API_URL=http://localhost:8000 python3 scripts/storyboard_e2e.py
```

- [ ] **Step 4: Run GREEN**

Run the README command. Expected: `skill_flow_check.py` covers Scenes 1–3/Acceptance 6 ordering, and `storyboard_e2e.py` covers Scenes 0, 4, 5, 5b, 6, 7 with same-query cache invalidation.

---

### Task 7: Full verification and finish evidence

**Files:**
- No new production files; update Bead metadata/notes only after verification.

- [ ] **Step 1: Run backend tests**

```bash
uv run --project backend pytest backend/tests -q
```

Expected: model tests pass; DB integration tests skip unless env is provided.

- [ ] **Step 2: Run CLI tests**

```bash
uv run --project cli pytest cli/tests -q
uv run --project cli pgal --help
```

Expected: PASS and help exits 0.

- [ ] **Step 3: Run skill-flow verifier**

```bash
python3 scripts/skill_flow_check.py
```

Expected: PASS.

- [ ] **Step 4: Run compose e2e**

```bash
docker compose up -d --build
PGAL_API_URL=http://localhost:8000 python3 scripts/storyboard_e2e.py
```

Expected: all storyboard checks pass.

- [ ] **Step 5: Inspect git diff**

```bash
git status --short --branch
git diff --stat
```

Expected: only intended MVP files, spec fixes, plan, and Beads metadata changed.

- [ ] **Step 6: Record Bead evidence**

Update `ralphthon-bje` with plan path, review evidence, verification commands, and completion status according to workflow after implementation-review/direct finish.
