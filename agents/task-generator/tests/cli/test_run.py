"""Tests for cli/run.py orchestrator."""

import json
import subprocess
import sys
from pathlib import Path

import yaml

import run as run_cli  # noqa: E402
import repo_map  # noqa: E402

UUID_A = "11111111-1111-1111-1111-111111111111"
PAGE_HTML = (
    "<h1>Page</h1><h2>Auth</h2><h3>Login</h3><ul><li>form</li></ul>"
)


def _write_map(tmp_path: Path, projects: dict) -> Path:
    p = tmp_path / "repo-map.yaml"
    p.write_text(yaml.safe_dump({"projects": projects}))
    return p


class FakeClient:
    def __init__(self, **kw):
        pass

    def get_page(self, project_id, page_id):
        return {"name": "Auth", "description_html": PAGE_HTML}

    def list_pages(self, project_id):
        return [{"id": "page-A", "name": "Auth", "access": 0}]

    def list_work_item_types(self, project_id):
        return [
            {"id": "t-epic", "name": "Epic"},
            {"id": "t-story", "name": "Story"},
            {"id": "t-task", "name": "Task"},
        ]

    def list_labels(self, project_id):
        return []

    def create_label(self, project_id, name, color="#888"):
        return {"id": f"lbl-{name}", "name": name}

    def search_work_items(self, project_id, **filters):
        return []


def _run(monkeypatch, capsys, argv):
    monkeypatch.setattr(sys, "argv", ["run.py", *argv])
    rc = run_cli.main()
    out, err = capsys.readouterr()
    return rc, out, err


def _setup_yaml_repo(monkeypatch, tmp_path):
    """Create a repo-map.yaml with UUID_A and a sibling git-checkout dir."""
    sibling_parent = tmp_path / "siblings"
    sibling_parent.mkdir()
    target = sibling_parent / "alpha"
    (target / ".git").mkdir(parents=True)
    monkeypatch.setattr(repo_map, "stellar_engine_parent", lambda: sibling_parent)
    map_path = _write_map(sibling_parent, {
        UUID_A: {"repo_name": "alpha", "git_url": "x", "workspace_prefix": "STELLAR"},
    })
    monkeypatch.setattr(repo_map, "DEFAULT_MAPPING_PATH", map_path)
    return target


def _setup_fakes(monkeypatch):
    monkeypatch.setattr(run_cli, "load_credentials", lambda: ("t", "https://h", "ws"))
    monkeypatch.setattr(run_cli, "PlaneClient", FakeClient)


def test_run_dry_run_end_to_end(monkeypatch, tmp_path, capsys):
    target = _setup_yaml_repo(monkeypatch, tmp_path)
    _setup_fakes(monkeypatch)
    rc, out, err = _run(monkeypatch, capsys, [
        UUID_A, "page-A", "--dry-run", "--run-id", "run01",
    ])
    assert rc == 0
    assert "master_preview:" in out
    assert "summary: epics=" in out
    work_dir = target / "runs" / "work" / "run01"
    assert (work_dir / "page.json").exists()
    assert (work_dir / "preflight.json").exists()
    assert (work_dir / "ir.json").exists()
    preview_dir = target / "runs" / "preview" / "run01"
    assert any(preview_dir.glob("*.master.preview.md"))
    assert any(preview_dir.glob("*.epic-*.preview.md"))


def test_run_writes_when_yes_passed(monkeypatch, tmp_path, capsys):
    target = _setup_yaml_repo(monkeypatch, tmp_path)
    _setup_fakes(monkeypatch)

    captured = {"write_argv": None, "grava_argv": None}

    import importlib
    write_mod = importlib.import_module("write")

    def fake_write_main():
        captured["write_argv"] = list(sys.argv)
        return 0

    monkeypatch.setattr(write_mod, "main", fake_write_main)

    grava_mod = importlib.import_module("grava")

    def fake_grava_main():
        captured["grava_argv"] = list(sys.argv)
        return 0

    monkeypatch.setattr(grava_mod, "main", fake_grava_main)

    rc, out, err = _run(monkeypatch, capsys, [
        UUID_A, "page-A", "--yes", "--run-id", "run02",
    ])
    assert rc == 0
    assert captured["write_argv"][0] == "write.py"
    run_id_idx = captured["write_argv"].index("--run-id") + 1
    assert captured["write_argv"][run_id_idx] == "run02"
    # Grava also fires after a successful write
    assert captured["grava_argv"] is not None
    assert captured["grava_argv"][0] == "grava.py"


def test_run_no_grava_short_circuits(monkeypatch, tmp_path, capsys):
    _setup_yaml_repo(monkeypatch, tmp_path)
    _setup_fakes(monkeypatch)

    import importlib
    write_mod = importlib.import_module("write")
    monkeypatch.setattr(write_mod, "main", lambda: 0)

    grava_mod = importlib.import_module("grava")
    grava_called = {"yes": False}

    def grava_main():
        grava_called["yes"] = True
        return 0

    monkeypatch.setattr(grava_mod, "main", grava_main)

    rc, out, err = _run(monkeypatch, capsys, [
        UUID_A, "page-A", "--yes", "--no-grava", "--run-id", "rng",
    ])
    assert rc == 0
    assert grava_called["yes"] is False


def test_run_skips_grava_if_plane_failed(monkeypatch, tmp_path, capsys):
    _setup_yaml_repo(monkeypatch, tmp_path)
    _setup_fakes(monkeypatch)

    import importlib
    write_mod = importlib.import_module("write")
    monkeypatch.setattr(write_mod, "main", lambda: 5)

    grava_mod = importlib.import_module("grava")
    grava_called = {"yes": False}

    def grava_main():
        grava_called["yes"] = True
        return 0

    monkeypatch.setattr(grava_mod, "main", grava_main)

    rc, out, err = _run(monkeypatch, capsys, [
        UUID_A, "page-A", "--yes", "--run-id", "rfail",
    ])
    assert rc == 5
    assert grava_called["yes"] is False


def test_run_blocks_writes_when_types_missing(monkeypatch, tmp_path, capsys):
    target = _setup_yaml_repo(monkeypatch, tmp_path)
    monkeypatch.setattr(run_cli, "load_credentials", lambda: ("t", "https://h", "ws"))

    class NoTypesClient(FakeClient):
        def list_work_item_types(self, project_id):
            return []  # epic/story/task all missing

    monkeypatch.setattr(run_cli, "PlaneClient", NoTypesClient)

    rc, out, err = _run(monkeypatch, capsys, [
        UUID_A, "page-A", "--yes", "--run-id", "run-no-types",
    ])
    assert rc == 4
    assert "missing" in err
    assert "epic" in err


def test_run_propagates_write_exit_code(monkeypatch, tmp_path, capsys):
    target = _setup_yaml_repo(monkeypatch, tmp_path)
    _setup_fakes(monkeypatch)

    import importlib
    write_mod = importlib.import_module("write")
    monkeypatch.setattr(write_mod, "main", lambda: 5)

    rc, out, err = _run(monkeypatch, capsys, [
        UUID_A, "page-A", "--yes", "--run-id", "run-fail",
    ])
    assert rc == 5


def test_run_target_repo_override(monkeypatch, tmp_path, capsys):
    override = tmp_path / "override-repo"
    override.mkdir()
    _setup_fakes(monkeypatch)
    rc, out, err = _run(monkeypatch, capsys, [
        UUID_A, "page-A", "--dry-run", "--target-repo", str(override),
        "--run-id", "run03",
    ])
    assert rc == 0
    preview_dir = override / "runs" / "preview" / "run03"
    assert any(preview_dir.glob("*.master.preview.md"))


def test_run_propagates_duplicate_exit_3(monkeypatch, tmp_path, capsys):
    target = _setup_yaml_repo(monkeypatch, tmp_path)
    monkeypatch.setattr(run_cli, "load_credentials", lambda: ("t", "https://h", "ws"))

    class DupClient(FakeClient):
        def list_pages(self, project_id):
            return [
                {"id": "page-A", "name": "Auth", "access": 0},
                {"id": "page-B", "name": "auth", "access": 0},
            ]

    monkeypatch.setattr(run_cli, "PlaneClient", DupClient)
    rc, out, err = _run(monkeypatch, capsys, [
        UUID_A, "page-A", "--dry-run", "--run-id", "run04",
    ])
    assert rc == 3
    assert "page-B" in err
    assert "--allow-duplicate-pages" in err
