from __future__ import annotations

from datetime import datetime
from typing import Iterable, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

TagKind = Literal["tag", "keyword"]
TechMatch = Literal["any", "all"]


def normalize_list(values: Iterable[str] | None) -> list[str]:
    if not values:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value).strip().lower()
        if not item or item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return normalized


def normalize_tech_stack(values: Iterable[str] | None) -> list[str]:
    return normalize_list(values)


def normalize_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return normalize_list(value.split(","))


class TagOut(BaseModel):
    name: str
    kind: TagKind


class ImageOut(BaseModel):
    image_id: UUID = Field(alias="id")
    profile_id: UUID | None = None
    url: str
    prompt: str | None = None
    mime_type: str
    width: int | None = None
    height: int | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class ProfileBase(BaseModel):
    name: str | None = None
    summary: str | None = None
    raw_text: str | None = None
    tech_stack: list[str] = Field(default_factory=list)
    domain: str | None = None
    tags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)

    @field_validator("tech_stack", mode="before")
    @classmethod
    def _normalize_tech_stack(cls, value: Iterable[str] | None) -> list[str]:
        return normalize_tech_stack(value)

    @field_validator("tags", "keywords", mode="before")
    @classmethod
    def _normalize_tags(cls, value: Iterable[str] | None) -> list[str]:
        return normalize_list(value)


class ProfileCreate(ProfileBase):
    name: str


class ProfileUpdate(ProfileBase):
    pass


class ProfileOut(ProfileBase):
    id: UUID
    name: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    images: list[ImageOut] = Field(default_factory=list)


class ProfileCreateResponse(ProfileOut):
    request_id: str
    status: Literal["created"] = "created"


class StatusResponse(BaseModel):
    id: UUID
    status: str


class ImageCreateResponse(ImageOut):
    pass


class SearchResponse(BaseModel):
    items: list[ProfileOut]
    limit: int
    offset: int


class TagUpdate(BaseModel):
    tags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)

    @field_validator("tags", "keywords", mode="before")
    @classmethod
    def _normalize_values(cls, value: Iterable[str] | None) -> list[str]:
        return normalize_list(value)


class ImgGenStatus(BaseModel):
    request_id: str
    status: str


class HealthOut(BaseModel):
    status: str
    db: str
    cache: str
