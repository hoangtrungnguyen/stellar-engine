"""Tests for cli/init_run.py."""

import sys
from pathlib import Path

import init_run  # noqa: E402  (path injected by conftest)


def _run(monkeypatch, capsys, argv):
    monkeypatch.setattr(sys, "argv", ["init_run.py", *argv])
    rc = init_run.main()
    out, err = capsys.readouterr()
    return rc, out, err


def test_init_run_creates_dir(monkeypatch, tmp_path, capsys):
    rc, out, err = _run(monkeypatch, capsys, ["--target-repo", str(tmp_path)])
    assert rc == 0
    work_dir = Path(out.strip())
    assert work_dir.exists()
    assert work_dir.parent == tmp_path / "runs" / "work"


def test_init_run_explicit_id(monkeypatch, tmp_path, capsys):
    rc, out, err = _run(monkeypatch, capsys, [
        "--target-repo", str(tmp_path), "--run-id", "myrun-001",
    ])
    assert rc == 0
    assert out.strip().endswith("/myrun-001")
    assert (tmp_path / "runs" / "work" / "myrun-001").is_dir()


def test_init_run_idempotent(monkeypatch, tmp_path, capsys):
    rc, out, _ = _run(monkeypatch, capsys, [
        "--target-repo", str(tmp_path), "--run-id", "stable",
    ])
    rc2, out2, _ = _run(monkeypatch, capsys, [
        "--target-repo", str(tmp_path), "--run-id", "stable",
    ])
    assert rc == rc2 == 0
    assert out.strip() == out2.strip()
