from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/profile_gallery")
    valkey_url: str = os.getenv("VALKEY_URL", "redis://localhost:6379/0")
    image_data_dir: Path = Path(os.getenv("IMAGE_DATA_DIR", "data/images"))
    max_image_bytes: int = int(os.getenv("MAX_IMAGE_BYTES", str(5 * 1024 * 1024)))


def get_settings() -> Settings:
    return Settings()
