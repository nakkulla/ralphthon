---
name: profile-gallery
description: Use when registering, updating, searching, browsing, or deleting project profiles in Project Profile Gallery, including representative image generation for a project profile.
---

# Profile Gallery

Use this skill to orchestrate Project Profile Gallery work through the `pgal` CLI. Codex owns analysis and `image_gen`; backend owns storage/search/image serving.

## Prerequisites

- Backend is running; default `PGAL_API_URL=http://localhost:8000`.
- `pgal` is available, usually via `uv run --project cli pgal` in this repo.
- Do not auto-install this skill into live `~/.codex/skills`; give install guidance only if user asks.

## Registration workflow

1. **Auto collect / 자동 수집** project signals:
   - user-provided text/file first;
   - current repo `README.md`, manifests, directory structure, git remote, recent commits;
   - `AGENTS.md`, Codex memory/context, current session facts.
2. Build a **registration draft / 등록 초안** JSON: `name`, `summary`, `raw_text`, `tech_stack`, `domain`, `tags`, `keywords`.
3. **사용자 컨펌 gate:** show draft and ask for confirmation/corrections. Do not call `image_gen` or any `pgal` write before explicit confirmation.
4. After confirmation, write an image prompt. See `references/image-prompting.md`.
5. Call `image_gen` to create the representative image.
6. Add image-derived keywords to the confirmed draft.
7. Save via CLI:

```bash
uv run --project cli pgal profile create --data - --json <<'JSON'
{ "name": "MoodBoard", "summary": "...", "tech_stack": ["fastapi"], "tags": ["music"], "keywords": ["waveform"] }
JSON
```

8. Parse `id` and `request_id`, then upload image:

```bash
uv run --project cli pgal image add <profile_id> --file <image_path> --prompt "<prompt>" --request-id <request_id> --json
```

9. Verify with `pgal search --json`, preferably using a tag and a tech filter.

## Search/browse workflow

Map user intent to CLI:

- natural text → `pgal search --q "..." --json`
- tag filter → `pgal search --tags music,ai --json`
- tech stack query → `pgal search --tech FastAPI,pgvector --tech-match all --json`
- browse tags → `pgal tag list --json`

Use `references/cli-commands.md` for full command shapes.

## Update workflow

1. Read current state: `pgal profile get <id> --json`.
2. Re-analyze or edit requested fields.
3. Apply partial update:

```bash
uv run --project cli pgal profile update <id> --data - --json <<'JSON'
{ "summary": "Updated summary" }
JSON
```

4. If image changes, run `image_gen` again and `pgal image add`.
5. Re-run search/get to verify.

## Delete workflow

Use `pgal profile delete <id> --json`, then verify the profile no longer appears in search and prior image URLs return 404 when practical.
