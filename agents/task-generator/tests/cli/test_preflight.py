"""Tests for cli/preflight.py."""

import json
import sys
from pathlib import Path

import preflight  # noqa: E402

PAGES_NO_DUP = [{"id": "page-A", "name": "Solo", "access": 0}]
PAGES_WITH_DUP = [
    {"id": "page-A", "name": "Title", "access": 0},
    {"id": "page-B", "name": "title", "access": 0},
]
TYPES_OK = [
    {"id": "t-epic", "name": "Epic"},
    {"id": "t-story", "name": "Story"},
    {"id": "t-task", "name": "Task"},
]
TYPES_MISSING_EPIC = [
    {"id": "t-story", "name": "Story"},
    {"id": "t-task", "name": "Task"},
]
LABELS = [{"id": "lbl-1", "name": "plane:STELLAR-1"}]


class FakeClient:
    def __init__(self, pages=PAGES_NO_DUP, types=TYPES_OK, labels=LABELS):
        self._pages = pages
        self._types = types
        self._labels = labels

    @classmethod
    def factory(cls, **kw):
        def _make(host=None, workspace=None, token=None):
            return cls(**kw)
        return _make

    def list_pages(self, project_id):
        return self._pages

    def list_work_item_types(self, project_id):
        return self._types

    def list_labels(self, project_id):
        return self._labels

    def get_project(self, project_id):
        return {"id": project_id, "name": "Fake", "identifier": "FAKE"}

    def create_label(self, project_id, name, color="#888"):
        new = {"id": f"lbl-{name}", "name": name}
        self._labels.append(new)
        return new

    def search_work_items(self, project_id, **filters):
        return []


def _run(monkeypatch, capsys, argv):
    monkeypatch.setattr(sys, "argv", ["preflight.py", *argv])
    rc = preflight.main()
    out, err = capsys.readouterr()
    return rc, out, err


def _setup(monkeypatch, fake_class):
    monkeypatch.setattr(preflight, "load_credentials", lambda: ("t", "https://h", "ws"))
    monkeypatch.setattr(preflight, "PlaneClient", fake_class)


def test_preflight_writes_preflight_json(monkeypatch, tmp_path, capsys):
    _setup(monkeypatch, FakeClient.factory())
    rc, out, err = _run(monkeypatch, capsys, [
        "proj", "page-A", "--work-dir", str(tmp_path),
    ])
    assert rc == 0
    blob = json.loads((tmp_path / "preflight.json").read_text())
    assert blob["type_uuids"]["epic"] == "t-epic"
    assert blob["duplicates"] == []
    assert blob["duplicates_bypassed"] is False


def test_preflight_halts_on_duplicate(monkeypatch, tmp_path, capsys):
    _setup(monkeypatch, FakeClient.factory(pages=PAGES_WITH_DUP))
    rc, out, err = _run(monkeypatch, capsys, [
        "proj", "page-A", "--work-dir", str(tmp_path),
    ])
    assert rc == 3
    assert "page-B" in err
    assert "title" in err
    assert "--allow-duplicate-pages" in err
    assert not (tmp_path / "preflight.json").exists()


def test_preflight_allow_duplicate_writes_with_flag(monkeypatch, tmp_path, capsys):
    _setup(monkeypatch, FakeClient.factory(pages=PAGES_WITH_DUP))
    rc, out, err = _run(monkeypatch, capsys, [
        "proj", "page-A", "--work-dir", str(tmp_path), "--allow-duplicate-pages",
    ])
    assert rc == 0
    blob = json.loads((tmp_path / "preflight.json").read_text())
    assert blob["duplicates_bypassed"] is True
    assert any(d["id"] == "page-B" for d in blob["duplicates"])
    assert "WARNING" in err


def test_preflight_missing_type_warns_but_passes(monkeypatch, tmp_path, capsys):
    """Phase 1 tolerates missing required types; emits WARNING + records in preflight.json."""
    import json
    _setup(monkeypatch, FakeClient.factory(types=TYPES_MISSING_EPIC))
    rc, out, err = _run(monkeypatch, capsys, [
        "proj", "page-A", "--work-dir", str(tmp_path),
    ])
    assert rc == 0
    assert "WARNING" in err and "epic" in err.lower()
    blob = json.loads((tmp_path / "preflight.json").read_text())
    assert "epic" in blob["missing_types"]
