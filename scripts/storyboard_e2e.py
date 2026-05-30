#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API_URL = os.getenv("PGAL_API_URL", "http://localhost:8000").rstrip("/")
PGAL = shlex.split(os.getenv("PGAL_BIN", "uv run --project cli pgal"))
ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".tmp" / "storyboard"


def scene(name: str) -> None:
    print(f"[scene] {name}")


def http_json(path: str) -> dict:
    with urllib.request.urlopen(f"{API_URL}{path}", timeout=10) as response:
        return json.loads(response.read().decode())


def http_status(path: str) -> int:
    try:
        with urllib.request.urlopen(f"{API_URL}{path}", timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def pgal(args: list[str], stdin: dict | None = None) -> dict:
    env = os.environ.copy()
    env["PGAL_API_URL"] = API_URL
    input_text = json.dumps(stdin, ensure_ascii=False) if stdin is not None else None
    proc = subprocess.run(
        PGAL + args,
        input=input_text,
        text=True,
        capture_output=True,
        cwd=ROOT,
        env=env,
    )
    if proc.returncode != 0:
        print(proc.stdout, end="")
        print(proc.stderr, end="", file=sys.stderr)
        raise SystemExit(f"pgal failed: {' '.join(PGAL + args)}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"non-json pgal output: {proc.stdout}") from exc


def main() -> None:
    scene("0 — infra health")
    health = http_json("/healthz")
    assert health == {"status": "ok", "db": "ok", "cache": "ok"}, health

    scene("1–3 — skill-flow contract")
    subprocess.run([sys.executable, "scripts/skill_flow_check.py"], cwd=ROOT, check=True)

    scene("4 — create profile and upload image")
    run_id = str(int(time.time() * 1000))
    unique_tag = f"storyboard-{run_id}"
    draft = {
        "name": f"MoodBoard-{run_id}",
        "summary": f"music ai playlist curation {unique_tag}",
        "raw_text": f"FastAPI pgvector music ai waveform gradient {unique_tag}",
        "tech_stack": ["FastAPI", " pgvector "],
        "domain": "music-ai",
        "tags": ["music", "ai", unique_tag],
        "keywords": ["waveform", "gradient", unique_tag],
    }
    created = pgal(["profile", "create", "--data", "-", "--json"], stdin=draft)
    profile_id = created["id"]
    request_id = created["request_id"]
    got = pgal(["profile", "get", profile_id, "--json"])
    assert got["tech_stack"] == ["fastapi", "pgvector"], got

    TMP.mkdir(parents=True, exist_ok=True)
    image = TMP / "moodboard.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    uploaded = pgal([
        "image", "add", profile_id,
        "--file", str(image),
        "--prompt", "album art waveform gradient",
        "--request-id", request_id,
        "--json",
    ])
    image_id = uploaded["image_id"]
    assert http_status(f"/images/{image_id}") == 200
    assert http_json(f"/imggen/{request_id}")["status"] == "stored"

    scene("5 — q/tag search")
    same_search_args = ["search", "--q", unique_tag, "--tags", unique_tag, "--tech", "FastAPI,pgvector", "--tech-match", "all", "--json"]
    search1 = pgal(same_search_args)
    assert search1["items"] and search1["items"][0]["id"] == profile_id, search1
    assert len(search1["items"][0]["images"]) == 1

    scene("5b — tech stack search")
    tech_search = pgal(["search", "--tech", "FastAPI,pgvector", "--tech-match", "all", "--json"])
    assert any(item["id"] == profile_id for item in tech_search["items"]), tech_search

    scene("6 — update invalidates same search")
    pgal(["profile", "update", profile_id, "--data", "-", "--json"], stdin={"summary": "music ai updated summary"})
    search2 = pgal(same_search_args)
    assert search2["items"][0]["summary"] == "music ai updated summary", search2

    scene("7 — delete invalidates search and image URL")
    pgal(["profile", "delete", profile_id, "--json"])
    search3 = pgal(same_search_args)
    assert all(item["id"] != profile_id for item in search3["items"]), search3
    assert http_status(f"/images/{image_id}") == 404
    print("storyboard-e2e: ok")


if __name__ == "__main__":
    main()
