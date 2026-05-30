from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx


class ApiError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class ApiClient:
    def __init__(self, api_url: str | None = None):
        self.api_url = (api_url or os.getenv("PGAL_API_URL") or "http://localhost:8000").rstrip("/")

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            with httpx.Client(base_url=self.api_url, timeout=30) as client:
                response = client.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            raise ApiError(str(exc)) from exc
        if response.status_code >= 400:
            detail: Any
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            raise ApiError(str(detail), response.status_code)
        if response.content:
            return response.json()
        return {}

    def profile_create(self, payload: dict[str, Any]) -> Any:
        return self._request("POST", "/profiles", json=payload)

    def profile_get(self, profile_id: str) -> Any:
        return self._request("GET", f"/profiles/{profile_id}")

    def profile_list(self) -> Any:
        return self._request("GET", "/profiles")

    def profile_update(self, profile_id: str, payload: dict[str, Any]) -> Any:
        return self._request("PATCH", f"/profiles/{profile_id}", json=payload)

    def profile_delete(self, profile_id: str) -> Any:
        return self._request("DELETE", f"/profiles/{profile_id}")

    def image_add(self, profile_id: str, file_path: Path, prompt: str | None, request_id: str | None = None) -> Any:
        data = {"prompt": prompt or ""}
        if request_id:
            data["request_id"] = request_id
        with file_path.open("rb") as handle:
            files = {"file": (file_path.name, handle)}
            return self._request("POST", f"/profiles/{profile_id}/images", data=data, files=files)

    def image_list(self, profile_id: str) -> Any:
        return self._request("GET", f"/profiles/{profile_id}/images")

    def image_delete(self, image_id: str) -> Any:
        return self._request("DELETE", f"/images/{image_id}")

    def tag_add(self, profile_id: str, tags: list[str] | None = None, keywords: list[str] | None = None) -> Any:
        return self._request("POST", f"/profiles/{profile_id}/tags", json={"tags": tags or [], "keywords": keywords or []})

    def tag_remove(self, profile_id: str, tags: list[str] | None = None, keywords: list[str] | None = None) -> Any:
        return self._request("DELETE", f"/profiles/{profile_id}/tags", json={"tags": tags or [], "keywords": keywords or []})

    def tag_list(self) -> Any:
        return self._request("GET", "/tags")

    def search(self, **params: Any) -> Any:
        clean = {key: value for key, value in params.items() if value not in (None, "")}
        return self._request("GET", "/search", params=clean)
