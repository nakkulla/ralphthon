#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

skill = Path("skills/profile-gallery/SKILL.md")
full_text = skill.read_text(encoding="utf-8")
text = full_text[full_text.index("## Registration workflow"):]
checks = [
    "Auto collect",
    "registration draft",
    "사용자 컨펌",
    "Do not call `image_gen` or any `pgal` write before explicit confirmation",
    "image_gen",
    "image-derived keywords",
    "pgal profile create --data - --json",
    "pgal image add <profile_id>",
    "--request-id <request_id>",
    "pgal search --json",
    "--tech FastAPI,pgvector",
    "~/.codex/skills",
]
missing = [needle for needle in checks if needle not in full_text]
if missing:
    print("Missing skill contract phrases:", file=sys.stderr)
    for needle in missing:
        print(f"- {needle}", file=sys.stderr)
    raise SystemExit(1)
order = [
    "Auto collect",
    "registration draft",
    "사용자 컨펌",
    "image_gen",
    "image-derived keywords",
    "pgal profile create --data - --json",
    "pgal image add <profile_id>",
    "pgal search --json",
]
positions = [text.index(needle) for needle in order]
if positions != sorted(positions):
    print("Registration workflow order is wrong", file=sys.stderr)
    raise SystemExit(1)
print("skill-flow: ok")
