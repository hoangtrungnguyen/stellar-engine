"""Tests for cli/render.py."""

import json
import sys
from pathlib import Path

import render  # noqa: E402


def _seed(tmp_path: Path, run_id: str, *, dups_bypassed: bool = False, n_epics: int = 1) -> Path:
    work_dir = tmp_path / "runs" / "work" / run_id
    work_dir.mkdir(parents=True)
    epics = []
    for i in range(n_epics):
        epics.append({
            "title": f"Epic {i}",
            "description_md": "Body",
            "spec_page_url": "https://x",
            "spec_page_id": "page-A",
            "open_questions": ["Q?"] if i == 0 else [],
            "risks": [],
            "related_refs": ["STELLAR-12"] if i == 0 else [],
            "stories": [
                {
                    "title": "Login",
                    "description_md": "",
                    "type_marker": None,
                    "related_refs": [],
                    "tasks": [
                        {"title": "form", "description_md": "", "type_marker": None, "related_refs": []},
                    ],
                },
            ],
        })
    (work_dir / "ir.json").write_text(json.dumps({
        "epics": epics,
        "warnings": [{"kind": "orphan_story", "detail": "stray heading"}],
        "page_title": "Master Page",
    }))
    duplicates = [{"id": "page-B", "name": "duplicate"}] if dups_bypassed else []
    (work_dir / "preflight.json").write_text(json.dumps({
        "type_uuids": {"epic": "t-epic", "story": "t-story", "task": "t-task"},
        "label_uuids": {},
        "duplicates": duplicates,
        "duplicates_bypassed": dups_bypassed,
    }))
    return work_dir


def _run(monkeypatch, capsys, argv):
    monkeypatch.setattr(sys, "argv", ["render.py", *argv])
    rc = render.main()
    out, err = capsys.readouterr()
    return rc, out, err


def test_render_writes_preview(monkeypatch, tmp_path, capsys):
    work_dir = _seed(tmp_path, "20260509-160234")
    rc, out, err = _run(monkeypatch, capsys, [
        "--work-dir", str(work_dir), "--target-repo", str(tmp_path),
    ])
    assert rc == 0
    master_path = Path(out.strip())
    assert master_path.exists()
    text = master_path.read_text()
    assert "Master Page" in text or "Master preview" in text
    assert "## Warnings" in text
    assert "orphan_story" in text
    epic_files = list(master_path.parent.glob("*.epic-*.preview.md"))
    assert len(epic_files) == 1


def test_render_multi_epic(monkeypatch, tmp_path, capsys):
    work_dir = _seed(tmp_path, "20260509-160234", n_epics=3)
    rc, out, err = _run(monkeypatch, capsys, [
        "--work-dir", str(work_dir), "--target-repo", str(tmp_path),
    ])
    assert rc == 0
    master_path = Path(out.strip())
    epic_files = sorted(master_path.parent.glob("*.epic-*.preview.md"))
    assert len(epic_files) == 3
    master_text = master_path.read_text()
    assert "Epic 0" in master_text and "Epic 1" in master_text and "Epic 2" in master_text


def test_render_with_bypassed_duplicates(monkeypatch, tmp_path, capsys):
    work_dir = _seed(tmp_path, "20260509-160234", dups_bypassed=True)
    rc, out, err = _run(monkeypatch, capsys, [
        "--work-dir", str(work_dir), "--target-repo", str(tmp_path),
    ])
    assert rc == 0
    text = Path(out.strip()).read_text()
    assert "Bypassed duplicate pages" in text
    assert "page-B" in text


def test_render_missing_ir_returns_1(monkeypatch, tmp_path, capsys):
    work_dir = tmp_path / "runs" / "work" / "x"
    work_dir.mkdir(parents=True)
    rc, out, err = _run(monkeypatch, capsys, [
        "--work-dir", str(work_dir), "--target-repo", str(tmp_path),
    ])
    assert rc == 1
    assert "missing required file" in err
