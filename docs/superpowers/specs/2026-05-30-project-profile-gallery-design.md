# Project Profile Gallery — 설계 스펙

> 상태: 브레인스토밍 self-review 핸드오프 (외부 spec-review 전)
> 작성일: 2026-05-30

## 1. 목적과 한 문장 요약

프로젝트 프로파일(자유 텍스트/마크다운)을 Codex 스킬이 분석해 `image_gen`으로 대표
이미지를 만들고, 프로파일·이미지에서 태그/키워드를 추출해 Docker 기반 PostgreSQL에
저장한다. Valkey를 캐시로 사용해 조회/검색 성능을 높이고, 태그 + Postgres FTS 검색과
CRUD API를 제공하며, 등록·수정·검색·삭제 전 과정을 단일 Codex CLI 스킬
(`profile-gallery`)로 구동한다.

이 스펙은 **전체 MVP가 끝까지 동작하는 것**을 목표로 한다. 성능 최적화는 비목표다.

## 2. 핵심 결정 (확정)

| 항목 | 결정 |
| --- | --- |
| 프로파일 의미 | **프로젝트 프로파일** (프로젝트 소개/스택을 분석해 대표 이미지) |
| 분석·이미지 생성 위치 | **Codex 스킬이 오케스트레이션** (분석·태그추출·`image_gen`은 Codex가, 저장/검색은 백엔드) |
| 검색 방식 | **태그 + Postgres FTS** (pgvector RAG는 비목표, 이미지만 확보) |
| 백엔드/CLI 스택 | **Python** — FastAPI(백엔드) + Typer(CLI) |
| 프로파일 소스 | **Codex 스킬이 자동 수집** (현재 레포 + Codex 메모리/컨텍스트) → 등록 초안 생성 → 사용자 컨펌. 수동 텍스트/마크다운 파일은 선택적 보강/우선 입력 |
| 이미지 저장 | **백엔드가 파일 저장 + URL 서빙**, DB엔 경로/메타데이터 |
| 스킬 구조 | **단일 통합 스킬** `profile-gallery` (등록/수정/검색/삭제 분기) |
| 스킬 구동 방식 | 스킬이 내부에서 **`pgal` CLI를 호출**해 입력·수정·검색·삭제 수행 |

## 3. 아키텍처

```
┌─ Codex CLI 런타임 ───────────────────────────────────────┐
│  Codex 스킬: profile-gallery (단일 통합 SKILL.md)        │
│   - 등록 플로우: 분석 → image_gen → pgal create/image add │
│   - 수정 플로우: pgal get → 재분석/편집 → pgal update      │
│   - 검색/삭제 플로우: pgal search / pgal profile delete    │
└───────────────────────┬─────────────────────────────────┘
                        │ subprocess (CLI 호출)
                  ┌─────▼─────┐  REST 호출만 (얇은 클라이언트)
                  │ pgal CLI  │  (Typer)
                  └─────┬─────┘
                        │ HTTP/JSON
        ┌───────────────▼────────────────────┐
        │ FastAPI 백엔드                      │
        │  /profiles · /images · /search      │
        │  /tags · /images/{id}(정적 서빙)    │
        └────┬───────────────────────┬────────┘
       ┌─────▼──────┐         ┌───────▼──────┐
       │ PostgreSQL │         │   Valkey     │
       │ FTS + 태그 │         │   캐시       │
       └────────────┘         └──────────────┘
       + 이미지 파일은 백엔드 data 볼륨에 저장 → /images/{id} 서빙
```

**역할 분리 원칙**

- **Codex(스킬)** = 지능: 프로파일 분석, 이미지 프롬프트 작성, 태그/키워드 추출.
- **백엔드(FastAPI)** = 저장·검색·서빙: DB·캐시·이미지 파일 관리, REST API.
- **CLI(`pgal`)** = 연결: 백엔드 REST를 호출하는 얇은 클라이언트. 스킬의 실행 도구.

`image_gen` 내장툴은 Codex 런타임에만 존재하므로 이미지 생성은 Codex가 담당한다.
이 분리 덕분에 백엔드는 LLM 키 없이 순수 저장/검색 서비스로 유지된다.

## 4. 데이터 모델 (PostgreSQL)

### 4.1 테이블

**profiles**

| 컬럼 | 타입 | 비고 |
| --- | --- | --- |
| id | uuid PK | `gen_random_uuid()` |
| name | text NOT NULL | 프로젝트명 |
| summary | text | 한두 문장 요약 |
| raw_text | text | 원본 프로파일 전문 |
| tech_stack | text[] | 기술 스택. 저장 시 lower/trim canonical 값으로 정규화(`FastAPI`→`fastapi`) |
| domain | text | 도메인 분류 |
| created_at | timestamptz | 기본 now() |
| updated_at | timestamptz | 갱신 시 갱신 |
| search_vector | tsvector | 생성열, GIN 인덱스 |

`search_vector`는 `name + summary + raw_text + array_to_string(tech_stack,' ')`를
`to_tsvector('simple', ...)`로 생성한다. `simple` config 사용 이유: 프로파일이
한/영 혼용일 수 있어 언어별 stemming(`english`)이 한국어를 제대로 처리하지 못하므로
언어 중립 토큰 매칭을 택한다.

**images**

| 컬럼 | 타입 | 비고 |
| --- | --- | --- |
| id | uuid PK | |
| profile_id | uuid FK → profiles(id) ON DELETE CASCADE | |
| file_path | text | 백엔드 data 볼륨 내부 경로 |
| url | text | `/images/{id}` |
| prompt | text | 생성에 쓴 프롬프트 |
| mime_type | text | 예: image/png |
| width | int | nullable |
| height | int | nullable |
| created_at | timestamptz | |

**tags**

| 컬럼 | 타입 | 비고 |
| --- | --- | --- |
| id | uuid PK | |
| name | text | |
| kind | text | `'tag'` 또는 `'keyword'` |
| | | UNIQUE(name, kind) |

**profile_tags** (M:N 조인)

| 컬럼 | 타입 |
| --- | --- |
| profile_id | uuid FK → profiles ON DELETE CASCADE |
| tag_id | uuid FK → tags ON DELETE CASCADE |
| | PK(profile_id, tag_id) |

태그와 키워드를 한 테이블에 `kind`로 구분한다. 이로써 전체 태그 브라우즈, 종류별
검색, 전역 태그 CRUD가 한 메커니즘으로 동작한다.

### 4.2 인덱스

- `profiles.search_vector` → GIN
- `profiles.tech_stack` → GIN (lower/trim canonical 배열 포함/겹침 검색용)
- `tags(name, kind)` → UNIQUE
- `profile_tags(tag_id)` → 보조 인덱스 (태그 역검색)

### 4.3 마이그레이션

MVP 최단경로로 단일 `backend/schema.sql`을 백엔드 기동 시 **idempotent**하게 적용한다
(`CREATE TABLE IF NOT EXISTS`, `CREATE EXTENSION IF NOT EXISTS pgcrypto`). 별도
마이그레이션 도구(Alembic)는 비목표.

## 5. 검색 (태그 + Postgres FTS)

`GET /search` 파라미터:

- `q`: 전문검색어 (FTS). `websearch_to_tsquery('simple', q)`로 변환, `ts_rank`로 정렬.
- `tags`: 콤마구분 태그 필터 (AND/OR는 `match=all|any`, 기본 any).
- `kind`: `tag|keyword|all` (기본 all) — 태그 필터 대상 종류.
- `tech`: 콤마구분 기술스택 필터. `profiles.tech_stack` 배열에 대해 매칭.
- `tech_match`: `any|all` (기본 any). `any`는 배열 겹침(`&&`), `all`은 배열 포함(`@>`).
- `limit`, `offset`: 페이지네이션.

`tech` 필터는 **1급 기능**이다. "어떤 기술스택을 가진 프로파일을 찾아줘"라는 조회가
FTS 부분일치에 의존하지 않고 `tech_stack` 배열 매칭으로 정확히 동작하도록 한다.
대소문자/표기 흔들림을 줄이기 위해 **쓰기 시점에 `tech_stack`을 lower/trim canonical 값으로 저장**한다. CLI/스킬 입력과 검색 파라미터도 같은 정규화 함수를 적용한다. 응답 표시도 canonical 값을 기본으로 반환한다(예: `FastAPI`, ` fastapi ` 입력은 모두 `fastapi`). 이 규칙으로 Postgres 배열 `&&`/`@>`와 GIN 인덱스가 대소문자 차이 없이 동작한다.

동작:

1. `q`가 있으면 FTS 조건 + `ts_rank` 정렬, 없으면 `updated_at desc`.
2. `tags`가 있으면 `profile_tags` 조인으로 필터.
3. `tech`가 있으면 `tech_stack` 배열 연산(`&&`/`@>`)으로 필터.
4. 위 조건들은 AND로 결합된다(예: `tech=FastAPI` + `tags=ai`).
5. 결과는 프로파일 + 첨부 이미지(url) + 태그/키워드 + tech_stack을 포함해 반환.
6. 결과를 Valkey `search:{정규화질의해시}`에 짧은 TTL로 캐싱.

## 6. Valkey 캐싱 전략

| 키 | 값 | TTL | 무효화 |
| --- | --- | --- | --- |
| `profile:{id}` | 프로파일 JSON | 300s | update/delete 시 삭제 |
| `search:{hash}` | 검색 결과 JSON | 60s | 프로파일/태그/이미지 쓰기 시 `search:*` 즉시 삭제 |
| `imggen:{request_id}` | 이미지 생성 요청 상태(`pending`→`stored`) | 600s | stored 후 만료 |

`imggen` 상태: CLI가 등록 시 `request_id`를 받아 이미지 업로드 전까지 상태를 추적할 수
있게 한다(브리프의 "이미지 생성 요청 상태 캐싱" 충족). 동기 흐름이므로 선택적 추적이며,
백엔드는 `GET /imggen/{request_id}`로 상태를 노출한다.

쓰기 작업(`POST/PATCH/DELETE /profiles`, 이미지 추가/삭제, 태그 추가/삭제)은 성공 후 `profile:{id}`와 `search:*`를 즉시 무효화한다. 구현은 Valkey `SCAN`으로 `search:*` 키를 찾아 삭제한다. MVP는 데이터량이 작으므로 패턴 삭제 비용을 허용하고, 검색 결과 stale 상태를 TTL까지 허용하지 않는다.

캐시 장애 시 백엔드는 캐시를 건너뛰고 DB로 폴백한다(캐시는 성능 보조이지 정합성 소스 아님). 캐시 무효화 실패는 요청 자체를 실패시키지 않되, 로그에 남기고 다음 조회는 DB authoritative 경로로 동작해야 한다.

## 7. API 표면 (FastAPI)

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| POST | `/profiles` | 프로파일 등록(구조화 JSON 본문) |
| GET | `/profiles` | 목록 |
| GET | `/profiles/{id}` | 단건 조회(캐시) |
| PATCH | `/profiles/{id}` | 부분 수정 |
| DELETE | `/profiles/{id}` | 삭제(이미지·태그 연쇄 정리) |
| POST | `/profiles/{id}/images` | 멀티파트 이미지 업로드. 선택 form 필드 `request_id`가 있으면 `imggen:{request_id}`를 `stored`로 갱신 |
| GET | `/profiles/{id}/images` | 프로파일 이미지 목록 |
| DELETE | `/images/{id}` | 이미지 삭제 |
| GET | `/images/{id}` | 이미지 정적 서빙 |
| POST | `/profiles/{id}/tags` | 태그/키워드 추가 |
| DELETE | `/profiles/{id}/tags` | 태그/키워드 제거 |
| GET | `/tags` | 전체 태그/키워드 브라우즈 |
| GET | `/search` | 검색 (5절) |
| GET | `/imggen/{request_id}` | 이미지 생성 요청 상태 |
| GET | `/healthz` | 헬스체크 |

요청/응답은 Pydantic 모델로 검증. `POST /profiles` 응답은 생성된 `id`와 `request_id`를 반환하고, 백엔드는 `imggen:{request_id}=pending`을 Valkey에 기록한다. `pgal image add`는 이 `request_id`를 `--request-id` 또는 JSON create 응답 파싱값으로 전달해 업로드와 생성 상태를 연결한다. 본문의 `tags`는 `tags` 테이블에 `kind='tag'`로,
`keywords`는 `kind='keyword'`로 upsert되고 `profile_tags`로 연결된다. `POST /profiles`
본문 예:

```json
{
  "name": "MoodBoard",
  "summary": "음악 감정 분석 기반 플레이리스트 자동 큐레이션",
  "raw_text": "MoodBoard: ...전문...",
  "tech_stack": ["Next.js", "FastAPI", "pgvector"],
  "domain": "music-ai",
  "tags": ["music", "ai", "web"],
  "keywords": ["감정분석", "플레이리스트", "큐레이션"]
}
```

## 8. CLI (`pgal`, Typer)

백엔드 REST를 호출하는 얇은 클라이언트. 기본 출력은 사람용 테이블, `--json`으로
기계 판독 출력(스킬이 파싱). API 주소는 `PGAL_API_URL`(기본 `http://localhost:8000`)
또는 `--api-url`.

| 명령 | 동작 |
| --- | --- |
| `pgal profile create --data <file\|-> --json` | `POST /profiles` (Codex가 만든 구조화 데이터) |
| `pgal profile get <id> [--json]` | `GET /profiles/{id}` |
| `pgal profile list` | `GET /profiles` |
| `pgal profile update <id> --data <file\|-> --json` | `PATCH /profiles/{id}` |
| `pgal profile delete <id>` | `DELETE /profiles/{id}` |
| `pgal image add <profile_id> --file <path> --prompt "..." [--request-id <id>]` | `POST /profiles/{id}/images` (request_id 전달 시 `imggen` 상태 `stored`) |
| `pgal image list <profile_id>` | `GET /profiles/{id}/images` |
| `pgal image delete <image_id>` | `DELETE /images/{id}` |
| `pgal tag add <profile_id> --tags a,b --keywords c,d` | `POST /profiles/{id}/tags` |
| `pgal tag remove <profile_id> --tags a` | `DELETE /profiles/{id}/tags` |
| `pgal search --q "..." --tags ... --kind tag --tech FastAPI,pgvector --tech-match any [--json]` | `GET /search` (q·태그·기술스택 필터) |

오류 시 비정상 종료코드 + 명확한 메시지. `--json` 모드에서는 오류도 JSON으로 출력.

## 9. Codex 스킬 (`profile-gallery`, 단일 통합)

저장소에 소스로 보관하고, `~/.codex/skills/`로의 설치는 **사용자 주도 install 안내**로
분리한다(라이브 `~/.codex`에 자동 설치하지 않음).

```
skills/profile-gallery/
├─ SKILL.md            # description + 워크플로 분기 + 핵심 pgal 요약
└─ references/
   ├─ cli-commands.md  # pgal 전체 명령 레퍼런스
   └─ image-prompting.md # 대표 이미지 프롬프트 가이드
```

**프로파일 소스 자동 수집 (등록의 0단계)**

사용자가 "내 프로파일 등록해줘"라고 하면 스킬이 다음에서 프로젝트 정보를 자동 수집한다:

- **현재 레포**: README, 매니페스트(`pyproject.toml`/`package.json`/`Cargo.toml` 등),
  디렉터리 구조, `git remote` URL, 최근 커밋, 언어 구성.
- **Codex 메모리/컨텍스트**: `AGENTS.md`, `~/.codex` 메모리, 현재 세션 지식.

소스 우선순위: **사용자가 직접 준 파일/텍스트 > 레포 신호 > Codex 메모리**. 수동 입력이
있으면 그것을 우선·보강에 사용하고, 없으면 자동 수집만으로 초안을 만든다.

SKILL.md 워크플로 분기:

- **(A) 등록**:
  0. **자동 수집**: 위 소스에서 프로젝트 정보 수집.
  1. 수집 내용 분석 → 구조화(name·summary·tech_stack·domain) + 태그/키워드 추출하여
     **등록 초안** 작성.
  2. **사용자 컨펌 게이트**: 초안을 사용자에게 제시하고 확인/수정을 받는다. 수정 요청 시
     반복하고, 확인된 경우에만 다음 단계로 진행한다.
  3. 이미지 프롬프트 작성 → `image_gen` 호출 → 이미지 설명에서 키워드 보강.
  4. `pgal profile create --data ... --json` → `pgal image add --request-id` → `pgal search --json`로 검증.
- **(B) 수정**: `pgal profile get --json`으로 현재 상태 조회 → 필드 재분석/편집(필요 시 이미지
  재생성) → `pgal profile update --data ... --json` / `pgal image add`.
- **(C) 검색/브라우즈**: 자연어 조회를 `pgal search --json` 호출로 매핑. 특히 "어떤 기술스택을
  가진 프로파일 찾아줘" 같은 요청은 `pgal search --tech <스택> --json`(필요 시 `--tags`/`--q`와
  결합)으로 변환해 실행하고, 결과를 사람이 읽기 좋게 정리해 보여준다. `pgal tag`로 태그
  브라우즈.
- **(D) 삭제**: `pgal profile delete`.

스킬 description은 "프로젝트 프로파일을 등록/수정/검색/삭제하고 대표 이미지를 생성한다"
범위로 작성해 트리거를 하나로 모은다.

## 10. 인프라 / 저장소 레이아웃

```
ralphthon/
├─ docker-compose.yml      # postgres + valkey + backend
├─ backend/
│  ├─ app/                 # FastAPI 앱 (main, routers, db, cache, models)
│  ├─ schema.sql
│  ├─ Dockerfile
│  ├─ pyproject.toml       # FastAPI/asyncpg/redis/python-multipart/pytest/httpx 의존성
│  └─ tests/
├─ cli/
│  ├─ pgal/                # Typer 앱
│  ├─ pyproject.toml       # Typer/httpx/pytest 의존성
│  └─ tests/
├─ skills/profile-gallery/ # SKILL.md + references/
├─ docs/superpowers/specs/ # 본 스펙 + 스토리보드
└─ README.md
```

`docker-compose.yml`:

- `postgres`: 이미지 `pgvector/pgvector:pg16` (확장은 미사용, 향후 RAG 여지만 확보),
  볼륨 `pgdata`.
- `valkey`: 이미지 `valkey/valkey:8`.
- `backend`: 로컬 Dockerfile, `DATABASE_URL`/`VALKEY_URL` 환경변수, 이미지 저장용 볼륨
  `imgdata` 마운트, 8000 포트 노출.

## 11. 에러 처리

- 백엔드: 404(없음)/409(중복)/422(검증) 표준화. 이미지 업로드는 MIME·크기 검증.
- DB/캐시 연결 실패는 `/healthz`에 반영, 캐시 실패는 DB 폴백.
- CLI: 백엔드 미응답·4xx/5xx 시 사람용 메시지 + 비정상 종료코드, `--json` 모드는 JSON 오류.
- 스킬: CLI 비정상 종료 시 중단하고 사용자에게 원인 보고.

## 12. 테스트 전략

- 백엔드: `pytest` + `httpx`로 라우터 단위/통합 (테스트용 임시 DB 또는 트랜잭션 롤백). profile delete 테스트는 DB row cascade뿐 아니라 data 볼륨 이미지 파일 삭제까지 검증한다.
- CLI: 목 HTTP 서버로 명령별 스모크, 종료코드/JSON 출력 검증.
- e2e: `docker compose up` 후 `/healthz` → 등록 → 이미지 업로드 → 검색 1회 왕복 확인.

## 13. 비목표 / 운영 확인 항목

- **비목표(MVP)**: pgvector/RAG 의미검색, BM25, 인증/인가, 멀티테넌시, 비동기 잡 큐,
  성능 최적화, 외부 오브젝트 스토리지.
- **운영 확인 필요(스펙 외부)**: 팀별 크레딧(약 150달러 추정)·OpenAI 크레딧·프로모션
  코드 적용 방식, 백엔드 배포 서버 위치. 녹취상 불명확했던 "피닷컴/프로모셔스/돌리 일스"는
  추정만 가능하므로 별도 확인 대상. 이들은 코드 산출물에 영향 없음.

## 14. 수용 기준 (Acceptance)

1. `docker compose up`으로 postgres·valkey·backend가 기동되고 `/healthz`가 200.
2. `pgal profile create`로 프로파일이 저장되고 `pgal profile get --json`으로 조회된다.
3. `pgal image add`로 업로드한 이미지가 `/images/{id}`로 서빙된다.
4. `pgal search --json`가 FTS(`--q`) + 태그(`--tags`) + **기술스택(`--tech`)** 필터를 결합해
   반환하고, 스킬을 통한 "특정 기술스택 보유 프로파일 조회"가 CLI 경유로 동작한다.
5. `pgal profile update`/`delete`가 동작하고 `profile:{id}` 및 `search:*` 캐시가 즉시 무효화된다. update 직후 같은 검색이 새 값을 반환하고, delete 직후 같은 검색이 삭제된 프로파일을 반환하지 않는다.
6. `profile-gallery` 단일 스킬의 등록 플로우가 레포 + Codex 메모리에서 정보를 **자동
   수집해 등록 초안을 만들고, 사용자 컨펌 후** `image_gen`으로 대표 이미지를 만들고,
   이미지 설명 기반 키워드 보강 후 `pgal profile create --data - --json`, `pgal image add --request-id`,
   `pgal search --json` 검증까지 end-to-end 동작한다.
7. `profile-gallery` 수정 플로우가 `pgal profile get --json`으로 현재 상태를 읽고,
   `pgal profile update --data ... --json` 또는 `pgal image add`를 통해 변경을 반영하며, 다음 검색에 즉시 반영된다.
8. `pgal profile delete`가 DB row뿐 아니라 이미지 파일까지 삭제하고, 삭제 후 `/images/{id}`가 404를 반환한다.
9. 백엔드 단위테스트, CLI 테스트, docker compose 기반 e2e 왕복(Scene 0–7)이 통과한다.

## 15. Execution lane

- **선택 레인**: `plan`
- **근거**: 백엔드(FastAPI)·CLI(Typer)·Codex 스킬·Docker Compose·DB 스키마가 얽힌
  다중 표면 작업으로, 구현 순서·의존성·표면 간 조율이 필요하다. 단일 스펙만으로 바로
  실행하기에는 작업 설계(task design)와 시퀀싱이 추가로 필요하다.
- **이 스펙이 plan을 대체하는가**: 아니오. 본 스펙은 설계 근거이며, 실행 전 `writing-plans`로
  구현 계획을 별도 작성한다.
- **확정 토폴로지**: `current_same_direct` (현재 checkout / same branch / direct finish). Bead `ralphthon-bje`의 metadata(`workspace_policy=current`, `branch_policy=same`, `finish_action=direct`)가 실행 권위다.
- 다음 게이트: 외부 spec-review → `writing-plans` → plan-review → `executing-plans` → implementation-review/검증 → direct finish.
