"""Unit tests for plane_client.py."""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import plane_client  # noqa: E402
from plane_client import PlaneClient, load_credentials  # noqa: E402


@pytest.fixture
def clean_env(monkeypatch):
    for var in ("PLANE_API_TOKEN", "PLANE_HOST", "PLANE_WORKSPACE",
                "PLANE_CONFIG", "PLANE_PROFILE"):
        monkeypatch.delenv(var, raising=False)


def test_load_credentials_env_wins(monkeypatch, tmp_path, clean_env):
    monkeypatch.setenv("PLANE_API_TOKEN", "envtoken")
    monkeypatch.setenv("PLANE_HOST", "https://env.example/")
    monkeypatch.setenv("PLANE_WORKSPACE", "envws")
    fake_cfg = tmp_path / "config.json"
    fake_cfg.write_text(json.dumps({"token": "filetoken", "workspace": "filews"}))
    monkeypatch.setattr(plane_client, "CONFIG_PATH", fake_cfg)

    token, host, ws = load_credentials()
    assert token == "envtoken"
    assert host == "https://env.example"
    assert ws == "envws"


def test_load_credentials_file_fallback(monkeypatch, tmp_path, clean_env):
    fake_cfg = tmp_path / "config.json"
    fake_cfg.write_text(json.dumps({
        "token": "filetoken",
        "host": "https://file.example",
        "workspace": "filews",
    }))
    monkeypatch.setattr(plane_client, "CONFIG_PATH", fake_cfg)

    token, host, ws = load_credentials()
    assert token == "filetoken"
    assert host == "https://file.example"
    assert ws == "filews"


def test_load_credentials_missing_raises(monkeypatch, tmp_path, clean_env):
    fake_cfg = tmp_path / "nonexistent.json"
    monkeypatch.setattr(plane_client, "CONFIG_PATH", fake_cfg)
    monkeypatch.setattr(plane_client, "CONFIG_DIR", tmp_path)
    with pytest.raises(RuntimeError, match="Missing Plane credentials"):
        load_credentials()


# ── PLANE_PROFILE / PLANE_CONFIG profile resolution ──────────────────────────


def test_resolve_plane_config_path_default(monkeypatch, clean_env):
    """No PLANE_CONFIG / PLANE_PROFILE → falls back to module-level CONFIG_PATH."""
    p = plane_client.resolve_plane_config_path()
    assert p == plane_client.CONFIG_PATH


def test_resolve_plane_config_path_profile(monkeypatch, tmp_path, clean_env):
    """PLANE_PROFILE=foo → ~/.config/plane/foo.json (under CONFIG_DIR)."""
    monkeypatch.setattr(plane_client, "CONFIG_DIR", tmp_path)
    monkeypatch.setenv("PLANE_PROFILE", "stellar-sandbox")
    p = plane_client.resolve_plane_config_path()
    assert p == tmp_path / "stellar-sandbox.json"


def test_resolve_plane_config_path_explicit_wins(monkeypatch, tmp_path, clean_env):
    """PLANE_CONFIG=/abs/path beats PLANE_PROFILE."""
    monkeypatch.setattr(plane_client, "CONFIG_DIR", tmp_path)
    monkeypatch.setenv("PLANE_PROFILE", "ignored")
    monkeypatch.setenv("PLANE_CONFIG", str(tmp_path / "custom.json"))
    p = plane_client.resolve_plane_config_path()
    assert p == tmp_path / "custom.json"


def test_load_credentials_via_profile(monkeypatch, tmp_path, clean_env):
    """PLANE_PROFILE=foo loads ~/.config/plane/foo.json instead of config.json."""
    monkeypatch.setattr(plane_client, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(plane_client, "CONFIG_PATH", tmp_path / "config.json")
    (tmp_path / "config.json").write_text(json.dumps({
        "token": "default-token", "workspace": "default-ws",
        "host": "https://default.example",
    }))
    (tmp_path / "stellar-sandbox.json").write_text(json.dumps({
        "token": "sandbox-token", "workspace": "stellar-sandbox",
        "host": "https://sandbox.example",
    }))
    monkeypatch.setenv("PLANE_PROFILE", "stellar-sandbox")

    token, host, ws = load_credentials()
    assert token == "sandbox-token"
    assert ws == "stellar-sandbox"
    assert host == "https://sandbox.example"


def test_load_credentials_via_explicit_config_path(monkeypatch, tmp_path, clean_env):
    """PLANE_CONFIG=<absolute path> loads from that exact file."""
    custom = tmp_path / "elsewhere" / "creds.json"
    custom.parent.mkdir()
    custom.write_text(json.dumps({
        "token": "elsewhere-token", "workspace": "elsewhere-ws",
    }))
    monkeypatch.setenv("PLANE_CONFIG", str(custom))

    token, _host, ws = load_credentials()
    assert token == "elsewhere-token"
    assert ws == "elsewhere-ws"


def test_load_credentials_env_overrides_profile_partial(monkeypatch, tmp_path, clean_env):
    """PLANE_API_TOKEN overrides the token from the profile file, but
    workspace still comes from the file if not set in env."""
    monkeypatch.setattr(plane_client, "CONFIG_DIR", tmp_path)
    (tmp_path / "stellar-sandbox.json").write_text(json.dumps({
        "token": "sandbox-token", "workspace": "stellar-sandbox",
    }))
    monkeypatch.setenv("PLANE_PROFILE", "stellar-sandbox")
    monkeypatch.setenv("PLANE_API_TOKEN", "env-override-token")

    token, _host, ws = load_credentials()
    assert token == "env-override-token"  # env wins for token
    assert ws == "stellar-sandbox"  # file wins for workspace


def test_url_builder():
    client = PlaneClient(host="https://api.plane.so", workspace="myws", token="xxx")
    url = client._url("projects/abc/pages/")
    assert url == "https://api.plane.so/api/v1/workspaces/myws/projects/abc/pages/"


def test_repr_redacts_token():
    client = PlaneClient(host="https://api.plane.so", workspace="myws", token="secret123")
    assert "secret123" not in repr(client)
    assert "redacted" in repr(client)


class _FakeResp:
    def __init__(self, status: int, body=None):
        self.status_code = status
        self._body = body
        self.headers = {}
        self.text = "" if body is None else json.dumps(body)
        self.content = self.text.encode()

    def json(self):
        return self._body


def _client_with_recorder(monkeypatch, responses):
    """Return (client, recorded_calls). `responses` is a list of (status, body)."""
    client = PlaneClient(host="https://api.plane.so", workspace="ws", token="t")
    recorded = []

    def fake_request(method, url, **kwargs):
        recorded.append({"method": method, "url": url, "kwargs": kwargs})
        status, body = responses.pop(0)
        return _FakeResp(status, body)

    monkeypatch.setattr(client._session, "request", fake_request)
    return client, recorded


def test_create_work_item_payload_shape(monkeypatch):
    client, recorded = _client_with_recorder(
        monkeypatch, [(201, {"id": "wi-1", "sequence_id": 12})]
    )
    out = client.create_work_item("proj", {"name": "T", "type_id": "epic-id"})
    assert out == {"id": "wi-1", "sequence_id": 12}
    assert recorded[0]["method"] == "POST"
    assert recorded[0]["url"].endswith("/projects/proj/work-items/")
    assert recorded[0]["kwargs"]["json"] == {"name": "T", "type_id": "epic-id"}


def test_update_work_item_uses_patch(monkeypatch):
    client, recorded = _client_with_recorder(monkeypatch, [(200, {"id": "wi-1"})])
    client.update_work_item("proj", "wi-1", {"description_html": "<p>x</p>"})
    assert recorded[0]["method"] == "PATCH"
    assert recorded[0]["url"].endswith("/projects/proj/work-items/wi-1/")
    assert recorded[0]["kwargs"]["json"] == {"description_html": "<p>x</p>"}


def test_delete_work_item_returns_none_on_204(monkeypatch):
    client, recorded = _client_with_recorder(monkeypatch, [(204, None)])
    out = client.delete_work_item("proj", "wi-1")
    assert out is None
    assert recorded[0]["method"] == "DELETE"
    assert recorded[0]["url"].endswith("/projects/proj/work-items/wi-1/")


# ── Epic endpoint (first-class, distinct from /work-items/) ────────────
def test_create_epic_hits_epics_endpoint(monkeypatch):
    """POST /projects/{pid}/epics/ — different path from /work-items/."""
    client, recorded = _client_with_recorder(
        monkeypatch, [(201, {"id": "epic-1", "sequence_id": 7})]
    )
    out = client.create_epic("proj", {"name": "Auth"})
    assert out == {"id": "epic-1", "sequence_id": 7}
    assert recorded[0]["method"] == "POST"
    assert recorded[0]["url"].endswith("/projects/proj/epics/")
    assert recorded[0]["kwargs"]["json"] == {"name": "Auth"}


def test_update_epic_uses_patch_on_epics_endpoint(monkeypatch):
    client, recorded = _client_with_recorder(monkeypatch, [(200, {"id": "epic-1"})])
    client.update_epic("proj", "epic-1", {"priority": "high"})
    assert recorded[0]["method"] == "PATCH"
    assert recorded[0]["url"].endswith("/projects/proj/epics/epic-1/")
    assert recorded[0]["kwargs"]["json"] == {"priority": "high"}


def test_delete_epic_hits_epics_endpoint(monkeypatch):
    client, recorded = _client_with_recorder(monkeypatch, [(204, None)])
    out = client.delete_epic("proj", "epic-1")
    assert out is None
    assert recorded[0]["method"] == "DELETE"
    assert recorded[0]["url"].endswith("/projects/proj/epics/epic-1/")


def test_add_comment_posts_html(monkeypatch):
    client, recorded = _client_with_recorder(monkeypatch, [(201, {"id": "c-1"})])
    out = client.add_comment("proj", "wi-1", "<p>hi</p>")
    assert out == {"id": "c-1"}
    assert recorded[0]["method"] == "POST"
    assert recorded[0]["url"].endswith("/projects/proj/work-items/wi-1/comments/")
    assert recorded[0]["kwargs"]["json"] == {"comment_html": "<p>hi</p>"}


def test_create_label_default_color(monkeypatch):
    client, recorded = _client_with_recorder(monkeypatch, [(201, {"id": "lbl-1"})])
    client.create_label("proj", "Bug")
    assert recorded[0]["kwargs"]["json"] == {"name": "Bug", "color": "#888"}


def test_request_passes_default_timeout(monkeypatch):
    """Without a timeout, a hung Plane connection blocks the writer indefinitely."""
    client, recorded = _client_with_recorder(monkeypatch, [(200, {"ok": True})])
    client.get_page("proj", "page")
    assert recorded[0]["kwargs"]["timeout"] == 30


def test_request_caller_can_override_timeout(monkeypatch):
    client, recorded = _client_with_recorder(monkeypatch, [(200, {})])
    client._request("GET", "projects/proj/pages/", timeout=5)
    assert recorded[0]["kwargs"]["timeout"] == 5


@pytest.mark.skipif(
    not os.environ.get("RUN_PLANE_INTEGRATION"),
    reason="Requires RUN_PLANE_INTEGRATION=1 + live Plane creds",
)
def test_get_page_smoke():
    token, host, ws = load_credentials()
    client = PlaneClient(host=host, workspace=ws, token=token)
    project_id = os.environ["TEST_PROJECT_ID"]
    page_id = os.environ["TEST_PAGE_ID"]
    page = client.get_page(project_id, page_id)
    assert "description_html" in page or "name" in page


@pytest.mark.skipif(
    not os.environ.get("RUN_PLANE_INTEGRATION"),
    reason="Requires RUN_PLANE_INTEGRATION=1 + live Plane creds",
)
def test_list_pages_smoke():
    token, host, ws = load_credentials()
    client = PlaneClient(host=host, workspace=ws, token=token)
    project_id = os.environ["TEST_PROJECT_ID"]
    pages = client.list_pages(project_id)
    assert isinstance(pages, list)
