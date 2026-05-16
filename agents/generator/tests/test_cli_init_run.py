"""Tests for `agents/generator/cli/init_run.py` (Phase E3a)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from generator.cli import init_run


def test_creates_run_dir_under_drafts_root(tmp_path, capsys):
    rc = init_run.main([
        "--project", "demo",
        "--drafts-root", str(tmp_path),
        "--run-id", "RID-1",
    ])
    assert rc == 0
    work = tmp_path / "demo" / "runs" / "RID-1"
    assert work.is_dir()
    assert (work / "run.json").exists()
    out = capsys.readouterr().out.strip()
    assert out == str(work)


def test_run_json_contents(tmp_path):
    init_run.main([
        "--project", "demo",
        "--drafts-root", str(tmp_path),
        "--run-id", "RID-1",
        "--source", "/path/to/spec.md",
    ])
    meta = json.loads((tmp_path / "demo" / "runs" / "RID-1" / "run.json").read_text())
    assert meta["project"] == "demo"
    assert meta["run_id"] == "RID-1"
    assert meta["source"] == "/path/to/spec.md"
    assert "started_at" in meta


def test_default_run_id_is_utc_timestamp(tmp_path, capsys):
    rc = init_run.main([
        "--project", "demo",
        "--drafts-root", str(tmp_path),
    ])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    # Last path component should look like 20YYMMDDTHHMMSSZ.
    last = Path(out).name
    assert last.startswith("20") and last.endswith("Z") and "T" in last


def test_mkdir_failure_exits_1(tmp_path, capsys, monkeypatch):
    def _raise(*_a, **_kw):
        raise OSError("simulated")

    monkeypatch.setattr(Path, "mkdir", _raise)
    rc = init_run.main([
        "--project", "demo",
        "--drafts-root", str(tmp_path),
        "--run-id", "RID",
    ])
    captured = capsys.readouterr()
    assert rc == 1
    assert "cannot create" in captured.err


def test_help_exits_zero():
    with pytest.raises(SystemExit) as exc:
        init_run.build_parser().parse_args(["--help"])
    assert exc.value.code == 0
