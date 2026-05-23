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

    def get_project(self, project_id):
        return {"id": project_id, "name": "Fake", "identifier": "FAKE"}

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
    # Epic uses /epics/ endpoint (no type_id); story+task are still required.
    assert "story" in err
    assert "task" in err


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


DEP_PAGE_HTML = (
    "<h1>Page</h1>"
    "<h2>Schema cleanup</h2><p>prep work</p>"
    "<h2>Auth migration</h2>"
    "<blockquote>Depends on: Schema cleanup</blockquote>"
)

CYCLE_PAGE_HTML = (
    "<h1>Page</h1>"
    "<h2>A</h2><blockquote>Depends on: B</blockquote>"
    "<h2>B</h2><blockquote>Depends on: A</blockquote>"
)


def test_run_writes_dep_graph_and_reorders(monkeypatch, tmp_path, capsys):
    target = _setup_yaml_repo(monkeypatch, tmp_path)
    _setup_fakes(monkeypatch)

    class DepClient(FakeClient):
        def get_page(self, project_id, page_id):
            return {"name": "DepPage", "description_html": DEP_PAGE_HTML}

    monkeypatch.setattr(run_cli, "PlaneClient", DepClient)

    rc, out, err = _run(monkeypatch, capsys, [
        UUID_A, "page-A", "--dry-run", "--run-id", "rundeps",
    ])
    assert rc == 0
    work_dir = target / "runs" / "work" / "rundeps"
    assert (work_dir / "dep_graph.json").exists()
    blob = json.loads((work_dir / "dep_graph.json").read_text())
    assert blob["reordered"] is True
    assert blob["epic_titles"] == ["Schema cleanup", "Auth migration"]
    assert any(
        e["src_epic_idx"] == 0 and e["dst_epic_idx"] == 1
        for e in blob["edges"]
    )
    # resolved_edges uses post-reorder ref_keys (Schema is now at index 0,
    # Auth at index 1 — same as original here since markdown order matched).
    assert blob["resolved_edges"]
    assert blob["resolved_edges"][0]["src_ref_key"] == "epic:0"
    assert blob["resolved_edges"][0]["dst_ref_key"] == "epic:1"


def test_run_resolved_edges_post_reorder(monkeypatch, tmp_path, capsys):
    """When markdown order disagrees with topo order, resolved_edges must
    point at the post-reorder ref_keys, not the original ones."""
    target = _setup_yaml_repo(monkeypatch, tmp_path)
    _setup_fakes(monkeypatch)

    # Markdown order: Auth then Schema; Auth depends on Schema.
    # Topo order: Schema (idx 0 post-reorder), Auth (idx 1 post-reorder).
    REORDER_HTML = (
        "<h1>Page</h1>"
        "<h2>Auth migration</h2>"
        "<blockquote>Depends on: Schema cleanup</blockquote>"
        "<h2>Schema cleanup</h2><p>prep work</p>"
    )

    class ReorderClient(FakeClient):
        def get_page(self, project_id, page_id):
            return {"name": "ReorderPage", "description_html": REORDER_HTML}

    monkeypatch.setattr(run_cli, "PlaneClient", ReorderClient)

    rc, out, err = _run(monkeypatch, capsys, [
        UUID_A, "page-A", "--dry-run", "--run-id", "runreorder",
    ])
    assert rc == 0
    work_dir = target / "runs" / "work" / "runreorder"
    blob = json.loads((work_dir / "dep_graph.json").read_text())
    assert blob["reordered"] is True
    # Schema comes first now.
    assert blob["epic_titles"][0] == "Schema cleanup"
    assert blob["epic_titles"][1] == "Auth migration"
    # resolved_edges should point at Schema (epic:0) → Auth (epic:1).
    assert len(blob["resolved_edges"]) == 1
    edge = blob["resolved_edges"][0]
    assert edge["src_ref_key"] == "epic:0"
    assert edge["dst_ref_key"] == "epic:1"
    assert edge["src_title"] == "Schema cleanup"
    assert edge["dst_title"] == "Auth migration"


def test_run_cycle_blocks_with_exit_7(monkeypatch, tmp_path, capsys):
    _setup_yaml_repo(monkeypatch, tmp_path)
    _setup_fakes(monkeypatch)

    class CycleClient(FakeClient):
        def get_page(self, project_id, page_id):
            return {"name": "CyclePage", "description_html": CYCLE_PAGE_HTML}

    monkeypatch.setattr(run_cli, "PlaneClient", CycleClient)

    rc, out, err = _run(monkeypatch, capsys, [
        UUID_A, "page-A", "--dry-run", "--run-id", "runcycle",
    ])
    assert rc == 7
    assert "cycle" in err.lower()


def test_run_allow_dep_cycles_continues(monkeypatch, tmp_path, capsys):
    target = _setup_yaml_repo(monkeypatch, tmp_path)
    _setup_fakes(monkeypatch)

    class CycleClient(FakeClient):
        def get_page(self, project_id, page_id):
            return {"name": "CyclePage", "description_html": CYCLE_PAGE_HTML}

    monkeypatch.setattr(run_cli, "PlaneClient", CycleClient)

    rc, out, err = _run(monkeypatch, capsys, [
        UUID_A, "page-A", "--dry-run", "--run-id", "runcycle-allow",
        "--allow-dep-cycles",
    ])
    assert rc == 0
    work_dir = target / "runs" / "work" / "runcycle-allow"
    blob = json.loads((work_dir / "dep_graph.json").read_text())
    assert blob["cycles"]


def test_run_strict_deps_fails_on_unresolved(monkeypatch, tmp_path, capsys):
    _setup_yaml_repo(monkeypatch, tmp_path)
    _setup_fakes(monkeypatch)

    class UnresolvedClient(FakeClient):
        def get_page(self, project_id, page_id):
            return {
                "name": "UnresolvedPage",
                "description_html": (
                    "<h1>Page</h1><h2>A</h2>"
                    "<blockquote>Depends on: Nonexistent</blockquote>"
                ),
            }

    monkeypatch.setattr(run_cli, "PlaneClient", UnresolvedClient)
    rc, out, err = _run(monkeypatch, capsys, [
        UUID_A, "page-A", "--dry-run", "--run-id", "runstrict",
        "--strict-deps",
    ])
    assert rc == 7
    assert "Unresolved" in err


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


# ── --source-md (local-md entry mode) ─────────────────────────────
SAMPLE_MD = """# Local Spec

## Auth
Login + signup.

### Sign up
As a user, I want to sign up.

- Build form
- Validate email
"""


def test_run_source_md_dry_run_skips_plane_fetch(monkeypatch, tmp_path, capsys):
    """--source-md reads a local file; no get_page / list_pages calls."""
    target = _setup_yaml_repo(monkeypatch, tmp_path)
    src_md = tmp_path / "spec.md"
    src_md.write_text(SAMPLE_MD)

    fetch_calls = {"get_page": 0, "list_pages": 0}

    class NoFetchClient(FakeClient):
        def get_page(self, *a, **kw):
            fetch_calls["get_page"] += 1
            raise AssertionError("get_page must not be called in --source-md mode")

        def list_pages(self, *a, **kw):
            fetch_calls["list_pages"] += 1
            raise AssertionError("list_pages must not be called in --source-md mode")

    monkeypatch.setattr(run_cli, "load_credentials", lambda: ("t", "https://h", "ws"))
    monkeypatch.setattr(run_cli, "PlaneClient", NoFetchClient)

    rc, out, err = _run(monkeypatch, capsys, [
        UUID_A, "--source-md", str(src_md), "--dry-run", "--run-id", "rmd1",
    ])
    assert rc == 0
    assert fetch_calls == {"get_page": 0, "list_pages": 0}
    # page.json reflects the local source.
    page_payload = json.loads((target / "runs" / "work" / "rmd1" / "page.json").read_text())
    assert page_payload["source_md_path"].endswith("spec.md")
    assert page_payload["spec_page_url"].startswith("file://")
    assert page_payload["title"] == "spec"


def test_run_source_md_synthesizes_stable_page_id(monkeypatch, tmp_path, capsys):
    """Two runs against the same source path get the same synthesized page_id."""
    _setup_yaml_repo(monkeypatch, tmp_path)
    src_md = tmp_path / "spec.md"
    src_md.write_text(SAMPLE_MD)

    monkeypatch.setattr(run_cli, "load_credentials", lambda: ("t", "https://h", "ws"))
    monkeypatch.setattr(run_cli, "PlaneClient", FakeClient)

    _run(monkeypatch, capsys, [
        UUID_A, "--source-md", str(src_md), "--dry-run", "--run-id", "rmdA",
    ])
    _run(monkeypatch, capsys, [
        UUID_A, "--source-md", str(src_md), "--dry-run", "--run-id", "rmdB",
    ])
    # Both runs land under the same target repo; both page.json files should
    # carry the same synthesized page_id.
    target = tmp_path / "siblings" / "alpha"
    a = json.loads((target / "runs" / "work" / "rmdA" / "page.json").read_text())
    b = json.loads((target / "runs" / "work" / "rmdB" / "page.json").read_text())
    assert a["page_id"].startswith("md-")
    assert a["page_id"] == b["page_id"]


def test_run_source_md_requires_md_extension(monkeypatch, tmp_path, capsys):
    _setup_yaml_repo(monkeypatch, tmp_path)
    src = tmp_path / "spec.txt"
    src.write_text("not markdown")
    monkeypatch.setattr(run_cli, "load_credentials", lambda: ("t", "https://h", "ws"))
    monkeypatch.setattr(run_cli, "PlaneClient", FakeClient)
    rc, out, err = _run(monkeypatch, capsys, [
        UUID_A, "--source-md", str(src), "--dry-run", "--run-id", "rmdx",
    ])
    assert rc == 1
    assert "only .md" in err


def test_run_source_md_file_not_found(monkeypatch, tmp_path, capsys):
    _setup_yaml_repo(monkeypatch, tmp_path)
    monkeypatch.setattr(run_cli, "load_credentials", lambda: ("t", "https://h", "ws"))
    monkeypatch.setattr(run_cli, "PlaneClient", FakeClient)
    rc, out, err = _run(monkeypatch, capsys, [
        UUID_A, "--source-md", str(tmp_path / "missing.md"),
        "--dry-run", "--run-id", "rmdmiss",
    ])
    assert rc == 1
    assert "file not found" in err


def test_run_source_md_mutex_with_page_id(monkeypatch, tmp_path, capsys):
    """Passing both page_id and --source-md errors out."""
    _setup_yaml_repo(monkeypatch, tmp_path)
    src = tmp_path / "spec.md"
    src.write_text(SAMPLE_MD)
    monkeypatch.setattr(run_cli, "load_credentials", lambda: ("t", "https://h", "ws"))
    monkeypatch.setattr(run_cli, "PlaneClient", FakeClient)
    import pytest
    with pytest.raises(SystemExit):
        _run(monkeypatch, capsys, [
            UUID_A, "page-A", "--source-md", str(src), "--dry-run",
        ])


def test_run_requires_page_id_or_source_md(monkeypatch, tmp_path, capsys):
    """Neither page_id nor --source-md → argparse error."""
    _setup_yaml_repo(monkeypatch, tmp_path)
    monkeypatch.setattr(run_cli, "load_credentials", lambda: ("t", "https://h", "ws"))
    monkeypatch.setattr(run_cli, "PlaneClient", FakeClient)
    import pytest
    with pytest.raises(SystemExit):
        _run(monkeypatch, capsys, [UUID_A, "--dry-run"])
