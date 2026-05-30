# Ralphthon

랄프톤 프로젝트.

## Project Profile Gallery MVP

FastAPI 백엔드 + PostgreSQL + Valkey + `pgal` CLI + `profile-gallery` Codex 스킬로 프로젝트 프로파일을 등록/검색/수정/삭제하고 대표 이미지를 저장한다.

### 로컬 기동

```bash
docker compose up -d --build
curl -s http://localhost:8000/healthz
```

정상 응답:

```json
{"status":"ok","db":"ok","cache":"ok"}
```

### CLI 개발 실행

```bash
export PGAL_API_URL=http://localhost:8000
uv run --project cli pgal --help
```

### Storyboard 검증

```bash
docker compose up -d --build
PGAL_API_URL=http://localhost:8000 python3 scripts/skill_flow_check.py
PGAL_API_URL=http://localhost:8000 python3 scripts/storyboard_e2e.py
```
