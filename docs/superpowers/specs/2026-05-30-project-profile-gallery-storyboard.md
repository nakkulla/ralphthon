# Project Profile Gallery — 동작 스토리보드

> 이 문서는 [설계 스펙](./2026-05-30-project-profile-gallery-design.md)이 끝까지
> 동작했을 때의 end-to-end 시나리오를 장면별로 보여준다. 명령/응답 예시는 설명을 위한
> 것이며 실제 구현 시 세부는 달라질 수 있다.

## 등장 요소

- **사람(팀원)**: 프로젝트 프로파일을 가진 해커톤 참가자.
- **Codex 스킬 `profile-gallery`**: 분석·이미지 생성·CLI 호출을 오케스트레이션.
- **`pgal` CLI**: 백엔드 REST를 호출하는 얇은 클라이언트.
- **백엔드(FastAPI) + PostgreSQL + Valkey**: 저장·검색·이미지 서빙.

전제: `docker compose up`으로 백엔드/DB/캐시가 떠 있고 `PGAL_API_URL`이 설정돼 있다.

---

## Scene 0 — 인프라 기동

```
$ docker compose up -d
$ curl -s localhost:8000/healthz
{"status":"ok","db":"ok","cache":"ok"}
```

postgres·valkey·backend가 기동되고 스키마(`schema.sql`)가 idempotent하게 적용된다.

---

## Scene 1 — 입력 (프로젝트 프로파일 작성)

팀원이 자유 형식으로 프로젝트를 소개하는 `moodboard.md`를 만든다.

```markdown
# MoodBoard
음악의 감정을 분석해 그 순간에 어울리는 플레이리스트를 자동 큐레이션하는 웹앱.
오디오 특징(템포·키·에너지)과 가사 감정을 결합해 무드 벡터를 만든다.
스택: Next.js, FastAPI, pgvector, Spotify API.
```

---

## Scene 2 — Codex 스킬 실행 (등록 플로우 A)

팀원이 Codex에서 스킬을 부른다:

> "`profile-gallery` 스킬로 moodboard.md 등록해줘"

스킬이 텍스트를 **분석 → 구조화**한다:

```json
{
  "name": "MoodBoard",
  "summary": "음악 감정 분석 기반 플레이리스트 자동 큐레이션 웹앱",
  "raw_text": "MoodBoard: ... (원문 전체)",
  "tech_stack": ["Next.js", "FastAPI", "pgvector", "Spotify API"],
  "domain": "music-ai",
  "tags": ["music", "ai", "web"],
  "keywords": ["감정분석", "플레이리스트", "큐레이션", "무드벡터"]
}
```

---

## Scene 3 — 대표 이미지 생성 (`image_gen`)

스킬이 프로젝트를 대표하는 이미지 프롬프트를 작성하고 내장 `image_gen`을 호출한다:

> 프롬프트: "A vibrant album-cover style emblem representing AI-driven music mood
> analysis — flowing audio waveforms blending into a colorful emotion gradient,
> modern, clean, app-icon composition."

생성물: `$CODEX_HOME/generated_images/moodboard.png`

스킬이 생성된 이미지 설명에서 키워드를 보강한다: `["album-art", "waveform", "gradient"]`
→ 최종 keywords에 합류.

---

## Scene 4 — 저장 (스킬 → `pgal` CLI → 백엔드)

스킬이 CLI를 호출해 프로파일을 등록한다:

```
$ pgal profile create --json - <<'JSON'
{ "name": "MoodBoard", "summary": "...", "tech_stack": [...],
  "domain": "music-ai", "tags": ["music","ai","web"],
  "keywords": ["감정분석","플레이리스트","큐레이션","무드벡터",
               "album-art","waveform","gradient"] }
JSON
{"id":"7c3f...","request_id":"req_91a2","status":"created"}
```

이어 이미지를 업로드한다:

```
$ pgal image add 7c3f... --file ~/.codex/generated_images/moodboard.png \
        --prompt "A vibrant album-cover style emblem ..."
{"image_id":"a14d...","url":"/images/a14d...","mime_type":"image/png"}
```

백엔드 내부 동작:

1. `POST /profiles` → profiles row 삽입, tags/keywords를 `tags`+`profile_tags`에 upsert,
   `search_vector` 자동 생성, `imggen:req_91a2 = pending`을 Valkey에 기록.
2. `POST /profiles/{id}/images` → 파일을 data 볼륨(`/data/images/a14d....png`)에 저장,
   images row 삽입, `imggen:req_91a2 = stored`로 갱신.

---

## Scene 5 — 검색/조회 (검색 플로우 C)

다른 팀원이 음악 AI 프로젝트를 찾는다:

```
$ pgal search --q "음악 ai" --tags music
NAME       SUMMARY                                  TAGS            IMAGE
MoodBoard  음악 감정 분석 기반 플레이리스트 큐레이션  music,ai,web    /images/a14d...
```

백엔드 동작:

1. `GET /search?q=음악 ai&tags=music` → Valkey `search:{hash}` 조회 → **미스**.
2. PostgreSQL에서 `websearch_to_tsquery('simple','음악 ai')` FTS + `profile_tags` 태그
   필터 결합, `ts_rank` 정렬.
3. 결과(프로파일 + 이미지 url + 태그)를 Valkey에 60s TTL로 캐싱 후 반환.

같은 검색을 다시 하면 Valkey **히트**로 즉시 응답한다. 단건 조회
`pgal profile get 7c3f...`는 `profile:{id}` 캐시를 활용한다.

이미지는 브라우저/뷰어에서 `http://localhost:8000/images/a14d...`로 바로 열린다.

---

## Scene 6 — 수정 (수정 플로우 B, 스킬 → CLI)

요약을 다듬고 싶을 때도 **스킬**을 통한다:

> "`profile-gallery`로 MoodBoard 요약을 더 명확하게 고쳐줘"

스킬 동작:

1. `pgal profile get 7c3f... --json`으로 현재 상태 조회.
2. 요약을 재작성(필요하면 이미지 재생성 후 `pgal image add`).
3. 반영:

```
$ pgal profile update 7c3f... --json - <<'JSON'
{ "summary": "오디오 특징과 가사 감정을 결합해 순간에 맞는 플레이리스트를 만드는 음악 AI 웹앱" }
JSON
{"id":"7c3f...","status":"updated"}
```

백엔드는 `search_vector`를 재생성하고 `profile:7c3f...` 캐시를 무효화한다. 다음 검색에
즉시 반영된다.

---

## Scene 7 — 삭제 (삭제 플로우 D)

```
$ pgal profile delete 7c3f...
{"id":"7c3f...","status":"deleted"}
```

연쇄 정리: images·profile_tags 행과 data 볼륨의 이미지 파일이 함께 제거되고, 관련 캐시
키가 무효화된다.

---

## 전체 흐름 요약

```
프로파일 작성 ─▶ Codex 스킬(분석) ─▶ image_gen(이미지) ─▶ 키워드 보강
      ─▶ pgal create/image add ─▶ 백엔드 저장(PG+파일) ─▶ Valkey 캐시
      ─▶ pgal search(태그+FTS) ─▶ 결과+이미지 URL
      ─▶ pgal update/delete(스킬 경유) ─▶ 재색인/캐시 무효화
```

입력(등록)과 수정 모두 **단일 `profile-gallery` 스킬**이 `pgal` CLI를 호출해 수행하며,
백엔드는 저장·검색·서빙만 담당한다.
