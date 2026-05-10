"""Tests for cli/parse.py."""

import json
import sys
from pathlib import Path

import parse as parse_cli  # noqa: E402  (avoid stdlib parser shadow; the module is `parse`)


SIMPLE_HTML = (
    "<h1>Page Title</h1>"
    "<h2>User Auth Flow</h2>"
    "<h3>Login</h3>"
    "<ul><li>Build login form</li><li>Validate credentials</li></ul>"
    "<h3>Logout</h3>"
    "<ul><li>Clear session</li></ul>"
)


def _run(monkeypatch, capsys, argv):
    monkeypatch.setattr(sys, "argv", ["parse.py", *argv])
    rc = parse_cli.main()
    out, err = capsys.readouterr()
    return rc, out, err


def _seed_page(work_dir: Path, html: str = SIMPLE_HTML) -> None:
    page = {
        "project_id": "proj",
        "page_id": "page-A",
        "title": "User Auth Flow",
        "description_html": html,
        "spec_page_url": "https://app.plane.so/ws/projects/proj/pages/page-A/",
        "fetched_at": "2026-05-09T16:02:34Z",
    }
    (work_dir / "page.json").write_text(json.dumps(page), encoding="utf-8")


def test_parse_writes_ir_json(monkeypatch, tmp_path, capsys):
    _seed_page(tmp_path)
    rc, out, err = _run(monkeypatch, capsys, ["--work-dir", str(tmp_path)])
    assert rc == 0
    ir = json.loads((tmp_path / "ir.json").read_text())
    assert len(ir["epics"]) == 1
    epic = ir["epics"][0]
    assert epic["title"] == "User Auth Flow"
    assert len(epic["stories"]) == 2
    assert epic["stories"][0]["title"] == "Login"
    assert len(epic["stories"][0]["tasks"]) == 2
    assert ir["warnings"] == []
    assert ir["page_title"] == "User Auth Flow"


def test_parse_warnings_propagate(monkeypatch, tmp_path, capsys):
    _seed_page(tmp_path, html="<h1>Title</h1><h3>Orphan</h3>")
    rc, out, err = _run(monkeypatch, capsys, ["--work-dir", str(tmp_path)])
    assert rc == 0
    ir = json.loads((tmp_path / "ir.json").read_text())
    kinds = [w["kind"] for w in ir["warnings"]]
    # Phase 4+: H3 before any H2 → no_h2 warning + implicit epic from H1
    assert "no_h2" in kinds


def test_parse_workspace_prefix(monkeypatch, tmp_path, capsys):
    _seed_page(tmp_path, html="<h1>T</h1><h2>Epic SPORT-12</h2><h3>Story</h3><ul><li>SPORT-9 task</li></ul>")
    rc, out, err = _run(monkeypatch, capsys, [
        "--work-dir", str(tmp_path), "--workspace-prefix", "SPORT",
    ])
    assert rc == 0
    ir = json.loads((tmp_path / "ir.json").read_text())
    epic = ir["epics"][0]
    assert "SPORT-12" in epic["related_refs"]
    task_refs = epic["stories"][0]["tasks"][0]["related_refs"]
    assert "SPORT-9" in task_refs


def test_parse_multi_epic(monkeypatch, tmp_path, capsys):
    _seed_page(
        tmp_path,
        html="<h1>P</h1><h2>EPIC-1</h2><h3>S1</h3><ul><li>t1</li></ul>"
             "<h2>EPIC-2</h2><h3>S2</h3><ul><li>t2</li></ul>",
    )
    rc, out, err = _run(monkeypatch, capsys, ["--work-dir", str(tmp_path)])
    assert rc == 0
    ir = json.loads((tmp_path / "ir.json").read_text())
    assert len(ir["epics"]) == 2
    assert ir["epics"][0]["title"] == "EPIC-1"
    assert ir["epics"][1]["title"] == "EPIC-2"


def test_parse_missing_page_json(monkeypatch, tmp_path, capsys):
    rc, out, err = _run(monkeypatch, capsys, ["--work-dir", str(tmp_path)])
    assert rc == 1
    assert "page.json" in err
