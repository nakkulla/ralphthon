import json
from pathlib import Path

from typer.testing import CliRunner

from pgal.main import app

runner = CliRunner()


class FakeClient:
    calls = []

    def __init__(self, api_url=None):
        self.api_url = api_url

    def profile_create(self, payload):
        self.calls.append(("profile_create", payload))
        return {"id": "p1", "request_id": "req1", "status": "created"}

    def profile_get(self, profile_id):
        self.calls.append(("profile_get", profile_id))
        return {"id": profile_id, "name": "MoodBoard"}

    def profile_list(self):
        self.calls.append(("profile_list",))
        return [{"id": "p1"}]

    def profile_update(self, profile_id, payload):
        self.calls.append(("profile_update", profile_id, payload))
        return {"id": profile_id, "status": "updated"}

    def profile_delete(self, profile_id):
        self.calls.append(("profile_delete", profile_id))
        return {"id": profile_id, "status": "deleted"}

    def image_add(self, profile_id, file_path, prompt, request_id=None):
        self.calls.append(("image_add", profile_id, str(file_path), prompt, request_id))
        return {"image_id": "i1", "url": "/images/i1"}

    def image_list(self, profile_id):
        self.calls.append(("image_list", profile_id))
        return [{"image_id": "i1"}]

    def image_delete(self, image_id):
        self.calls.append(("image_delete", image_id))
        return {"id": image_id, "status": "deleted"}

    def tag_add(self, profile_id, tags=None, keywords=None):
        self.calls.append(("tag_add", profile_id, tags, keywords))
        return {"id": profile_id, "tags": tags or [], "keywords": keywords or []}

    def tag_remove(self, profile_id, tags=None, keywords=None):
        self.calls.append(("tag_remove", profile_id, tags, keywords))
        return {"id": profile_id, "tags": [], "keywords": []}

    def tag_list(self):
        self.calls.append(("tag_list",))
        return [{"name": "music", "kind": "tag"}]

    def search(self, **params):
        self.calls.append(("search", params))
        return {"items": [{"id": "p1"}], "limit": 20, "offset": 0}


def setup_fake(monkeypatch):
    FakeClient.calls = []
    monkeypatch.setattr("pgal.main.ApiClient", FakeClient)


def test_profile_create_reads_stdin_and_prints_json(monkeypatch):
    setup_fake(monkeypatch)
    result = runner.invoke(app, ["profile", "create", "--data", "-", "--json"], input='{"name":"MoodBoard"}')
    assert result.exit_code == 0
    assert json.loads(result.stdout)["request_id"] == "req1"
    assert FakeClient.calls == [("profile_create", {"name": "MoodBoard"})]


def test_profile_get_list_update_delete_json(monkeypatch):
    setup_fake(monkeypatch)
    assert json.loads(runner.invoke(app, ["profile", "get", "p1", "--json"]).stdout)["id"] == "p1"
    assert json.loads(runner.invoke(app, ["profile", "list", "--json"]).stdout)[0]["id"] == "p1"
    assert json.loads(runner.invoke(app, ["profile", "update", "p1", "--data", "-", "--json"], input='{"summary":"new"}').stdout)["status"] == "updated"
    assert json.loads(runner.invoke(app, ["profile", "delete", "p1", "--json"]).stdout)["status"] == "deleted"


def test_image_tag_and_search_commands(monkeypatch, tmp_path):
    setup_fake(monkeypatch)
    image = tmp_path / "mood.png"
    image.write_bytes(b"png")
    assert json.loads(runner.invoke(app, ["image", "add", "p1", "--file", str(image), "--prompt", "album", "--request-id", "req1", "--json"]).stdout)["image_id"] == "i1"
    assert json.loads(runner.invoke(app, ["image", "list", "p1", "--json"]).stdout)[0]["image_id"] == "i1"
    assert json.loads(runner.invoke(app, ["image", "delete", "i1", "--json"]).stdout)["status"] == "deleted"
    assert json.loads(runner.invoke(app, ["tag", "add", "p1", "--tags", "music,ai", "--keywords", "waveform", "--json"]).stdout)["tags"] == ["music", "ai"]
    assert json.loads(runner.invoke(app, ["tag", "remove", "p1", "--tags", "music", "--json"]).stdout)["tags"] == []
    assert json.loads(runner.invoke(app, ["tag", "list", "--json"]).stdout)[0]["name"] == "music"
    out = runner.invoke(app, ["search", "--q", "music ai", "--tags", "music", "--tech", "FastAPI,pgvector", "--tech-match", "all", "--json"])
    assert out.exit_code == 0
    assert FakeClient.calls[-1] == ("search", {"q": "music ai", "tags": "music", "kind": "all", "match": "any", "tech": "FastAPI,pgvector", "tech_match": "all", "limit": 20, "offset": 0})


def test_json_error_mode(monkeypatch):
    class BrokenClient(FakeClient):
        def profile_get(self, profile_id):
            raise RuntimeError("backend unavailable")

    monkeypatch.setattr("pgal.main.ApiClient", BrokenClient)
    result = runner.invoke(app, ["profile", "get", "missing", "--json"])
    assert result.exit_code != 0
    assert json.loads(result.stdout)["error"] == "backend unavailable"
