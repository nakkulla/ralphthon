from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from .client import ApiClient

app = typer.Typer(no_args_is_help=True)
profile_app = typer.Typer(no_args_is_help=True)
image_app = typer.Typer(no_args_is_help=True)
tag_app = typer.Typer(no_args_is_help=True)
app.add_typer(profile_app, name="profile")
app.add_typer(image_app, name="image")
app.add_typer(tag_app, name="tag")


def _client(api_url: str | None = None) -> ApiClient:
    return ApiClient(api_url=api_url)


def _read_json(source: str) -> dict[str, Any]:
    if source == "-":
        content = typer.get_text_stream("stdin").read()
    else:
        content = Path(source).read_text()
    return json.loads(content)


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _emit(result: Any, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(result, ensure_ascii=False))
        return
    if isinstance(result, list):
        for item in result:
            typer.echo(_one_line(item))
    elif isinstance(result, dict):
        typer.echo(_one_line(result))
    else:
        typer.echo(str(result))


def _one_line(item: dict[str, Any]) -> str:
    for key in ("name", "id", "image_id", "status", "url"):
        if key in item and item[key] is not None:
            return str(item[key])
    return json.dumps(item, ensure_ascii=False)


def _run(action, json_output: bool) -> None:
    try:
        _emit(action(), json_output)
    except Exception as exc:  # CLI boundary: present clean errors.
        if json_output:
            typer.echo(json.dumps({"error": str(exc)}, ensure_ascii=False))
        else:
            typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)


@profile_app.command("create")
def profile_create(
    data: str = typer.Option(..., "--data", help="JSON file path, or - for stdin."),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
    api_url: str | None = typer.Option(None, "--api-url"),
):
    _run(lambda: _client(api_url).profile_create(_read_json(data)), json_output)


@profile_app.command("get")
def profile_get(profile_id: str, json_output: bool = typer.Option(False, "--json"), api_url: str | None = typer.Option(None, "--api-url")):
    _run(lambda: _client(api_url).profile_get(profile_id), json_output)


@profile_app.command("list")
def profile_list(json_output: bool = typer.Option(False, "--json"), api_url: str | None = typer.Option(None, "--api-url")):
    _run(lambda: _client(api_url).profile_list(), json_output)


@profile_app.command("update")
def profile_update(
    profile_id: str,
    data: str = typer.Option(..., "--data", help="JSON file path, or - for stdin."),
    json_output: bool = typer.Option(False, "--json"),
    api_url: str | None = typer.Option(None, "--api-url"),
):
    _run(lambda: _client(api_url).profile_update(profile_id, _read_json(data)), json_output)


@profile_app.command("delete")
def profile_delete(profile_id: str, json_output: bool = typer.Option(False, "--json"), api_url: str | None = typer.Option(None, "--api-url")):
    _run(lambda: _client(api_url).profile_delete(profile_id), json_output)


@image_app.command("add")
def image_add(
    profile_id: str,
    file_path: Path = typer.Option(..., "--file", exists=True, dir_okay=False),
    prompt: str | None = typer.Option(None, "--prompt"),
    request_id: str | None = typer.Option(None, "--request-id"),
    json_output: bool = typer.Option(False, "--json"),
    api_url: str | None = typer.Option(None, "--api-url"),
):
    _run(lambda: _client(api_url).image_add(profile_id, file_path, prompt, request_id), json_output)


@image_app.command("list")
def image_list(profile_id: str, json_output: bool = typer.Option(False, "--json"), api_url: str | None = typer.Option(None, "--api-url")):
    _run(lambda: _client(api_url).image_list(profile_id), json_output)


@image_app.command("delete")
def image_delete(image_id: str, json_output: bool = typer.Option(False, "--json"), api_url: str | None = typer.Option(None, "--api-url")):
    _run(lambda: _client(api_url).image_delete(image_id), json_output)


@tag_app.command("add")
def tag_add(
    profile_id: str,
    tags: str | None = typer.Option(None, "--tags"),
    keywords: str | None = typer.Option(None, "--keywords"),
    json_output: bool = typer.Option(False, "--json"),
    api_url: str | None = typer.Option(None, "--api-url"),
):
    _run(lambda: _client(api_url).tag_add(profile_id, _csv(tags), _csv(keywords)), json_output)


@tag_app.command("remove")
def tag_remove(
    profile_id: str,
    tags: str | None = typer.Option(None, "--tags"),
    keywords: str | None = typer.Option(None, "--keywords"),
    json_output: bool = typer.Option(False, "--json"),
    api_url: str | None = typer.Option(None, "--api-url"),
):
    _run(lambda: _client(api_url).tag_remove(profile_id, _csv(tags), _csv(keywords)), json_output)


@tag_app.command("list")
def tag_list(json_output: bool = typer.Option(False, "--json"), api_url: str | None = typer.Option(None, "--api-url")):
    _run(lambda: _client(api_url).tag_list(), json_output)


@app.command("search")
def search(
    q: str | None = typer.Option(None, "--q"),
    tags: str | None = typer.Option(None, "--tags"),
    kind: str = typer.Option("all", "--kind"),
    match: str = typer.Option("any", "--match"),
    tech: str | None = typer.Option(None, "--tech"),
    tech_match: str = typer.Option("any", "--tech-match"),
    limit: int = typer.Option(20, "--limit"),
    offset: int = typer.Option(0, "--offset"),
    json_output: bool = typer.Option(False, "--json"),
    api_url: str | None = typer.Option(None, "--api-url"),
):
    _run(lambda: _client(api_url).search(q=q, tags=tags, kind=kind, match=match, tech=tech, tech_match=tech_match, limit=limit, offset=offset), json_output)


if __name__ == "__main__":
    app()
