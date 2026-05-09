"""Tests for cli/fetch.py."""

import json
import sys
from pathlib import Path

import fetch  # noqa: E402
from plane_client import PlaneClientError


class FakeClient:
    def __init__(self, *a, **kw):
        pass

    def get_page(self, project_id, page_id):
        return {"name": "User Auth Flow", "description_html": "<p>hi</p>"}


def _run(monkeypatch, capsys, argv):
    monkeypatch.setattr(sys, "argv", ["fetch.py", *argv])
    rc = fetch.main()
    out, err = capsys.readouterr()
    return rc, out, err


def test_fetch_writes_page_json(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(fetch, "load_credentials", lambda: ("t", "https://h", "ws"))
    monkeypatch.setattr(fetch, "PlaneClient", FakeClient)
    rc, out, err = _run(monkeypatch, capsys, [
        "proj-uuid", "page-uuid", "--work-dir", str(tmp_path),
    ])
    assert rc == 0
    page_json = tmp_path / "page.json"
    assert page_json.exists()
    blob = json.loads(page_json.read_text())
    assert blob["title"] == "User Auth Flow"
    assert blob["description_html"] == "<p>hi</p>"
    assert blob["page_id"] == "page-uuid"
    assert "spec_page_url" in blob
    assert out.strip() == str(page_json)


def test_fetch_404_returns_1(monkeypatch, tmp_path, capsys):
    class Boom(FakeClient):
        def get_page(self, project_id, page_id):
            raise PlaneClientError(404, "not found", "https://h/api/v1/.../pages/x/")

    monkeypatch.setattr(fetch, "load_credentials", lambda: ("t", "https://h", "ws"))
    monkeypatch.setattr(fetch, "PlaneClient", Boom)
    rc, out, err = _run(monkeypatch, capsys, [
        "proj-uuid", "page-uuid", "--work-dir", str(tmp_path),
    ])
    assert rc == 1
    assert "404" in err
    assert "/pages/x/" in err


def test_fetch_missing_creds_returns_1(monkeypatch, tmp_path, capsys):
    def boom():
        raise RuntimeError("Missing Plane credentials...")
    monkeypatch.setattr(fetch, "load_credentials", boom)
    rc, out, err = _run(monkeypatch, capsys, [
        "proj-uuid", "page-uuid", "--work-dir", str(tmp_path),
    ])
    assert rc == 1
    assert "Missing Plane credentials" in err
