"""Tests for `agents/generator/cli/render.py` (Phase E2)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from generator.cli import render as render_cli


_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample_outline.json"


def _seed_outline(work_dir: Path, *, wrap_envelope: bool = False) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    raw = json.loads(_FIXTURE.read_text())
    payload = {"run_id": "RID-1", "source": "spec.md", "outline": raw} if wrap_envelope else raw
    (work_dir / "outline.json").write_text(json.dumps(payload))


def test_happy_path_writes_drafts_and_manifest(tmp_path, capsys):
    _seed_outline(tmp_path)
    rc = render_cli.main([
        "--work-dir", str(tmp_path),
        "--system-name", "Demo",
        "--source", "spec.md",
    ])
    assert rc == 0
    drafts_dir = tmp_path / "drafts"
    files = sorted(p.name for p in drafts_dir.glob("*.md"))
    assert len(files) == 2
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["system_name"] == "Demo"
    assert manifest["confidence"] == 0.78
    assert {d["epic_title"] for d in manifest["drafts"]} == {"Court Booking", "Cancellations"}


def test_accepts_envelope_payload(tmp_path):
    _seed_outline(tmp_path, wrap_envelope=True)
    rc = render_cli.main([
        "--work-dir", str(tmp_path),
        "--system-name", "Demo",
    ])
    assert rc == 0


def test_missing_outline_exits_1(tmp_path, capsys):
    rc = render_cli.main([
        "--work-dir", str(tmp_path),
        "--system-name", "Demo",
    ])
    captured = capsys.readouterr()
    assert rc == 1
    assert "outline.json not found" in captured.err


def test_malformed_outline_json_exits_1(tmp_path, capsys):
    (tmp_path).mkdir(parents=True, exist_ok=True)
    (tmp_path / "outline.json").write_text("{not json")
    rc = render_cli.main([
        "--work-dir", str(tmp_path),
        "--system-name", "Demo",
    ])
    captured = capsys.readouterr()
    assert rc == 1
    assert "cannot read" in captured.err


def test_invalid_outline_shape_exits_1(tmp_path, capsys):
    """Story dict missing the required `title` key → exit 1 with helpful msg."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "outline.json").write_text(json.dumps(
        {"epics": [{"title": "X", "stories": [{"depends_on": []}]}]}
    ))
    rc = render_cli.main([
        "--work-dir", str(tmp_path),
        "--system-name", "Demo",
    ])
    captured = capsys.readouterr()
    assert rc == 1
    assert "invalid outline shape" in captured.err


def test_render_write_error_exits_2(tmp_path, capsys, monkeypatch):
    _seed_outline(tmp_path)
    original_write_text = Path.write_text

    def _raise_on_md(self, *args, **kwargs):
        if self.suffix == ".md":
            raise OSError("disk full (simulated)")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _raise_on_md)
    rc = render_cli.main([
        "--work-dir", str(tmp_path),
        "--system-name", "Demo",
    ])
    captured = capsys.readouterr()
    assert rc == 2
    assert "cannot write drafts" in captured.err


def test_help_exits_zero():
    with pytest.raises(SystemExit) as exc:
        render_cli.build_parser().parse_args(["--help"])
    assert exc.value.code == 0
