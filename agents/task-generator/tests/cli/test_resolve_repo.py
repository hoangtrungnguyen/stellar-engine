"""Tests for cli/resolve_repo.py."""

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import resolve_repo  # noqa: E402  (path injected by conftest)
import repo_map  # noqa: E402

UUID_A = "11111111-1111-1111-1111-111111111111"


def _write_map(tmp_path: Path, projects: dict) -> Path:
    p = tmp_path / "repo-map.yaml"
    p.write_text(yaml.safe_dump({"projects": projects}))
    return p


def _run(monkeypatch, capsys, argv, expect_exit=None):
    monkeypatch.setattr(sys, "argv", ["resolve_repo.py", *argv])
    if expect_exit is None:
        rc = resolve_repo.main()
    else:
        rc = resolve_repo.main()
    out, err = capsys.readouterr()
    return rc, out, err


def test_resolve_prints_path_when_existing(monkeypatch, tmp_path, capsys):
    target = tmp_path / "alpha"
    (target / ".git").mkdir(parents=True)
    monkeypatch.setattr(repo_map, "stellar_engine_parent", lambda: tmp_path)
    map_path = _write_map(tmp_path, {
        UUID_A: {"repo_name": "alpha", "git_url": "x", "workspace_prefix": "A"},
    })
    rc, out, err = _run(monkeypatch, capsys, [UUID_A, "--mapping-path", str(map_path)])
    assert rc == 0
    assert out.strip() == str(target)
    assert "Cloned" not in err


def test_resolve_clones_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(repo_map, "stellar_engine_parent", lambda: tmp_path)
    map_path = _write_map(tmp_path, {
        UUID_A: {"repo_name": "alpha", "git_url": "git@x:a.git", "workspace_prefix": "A"},
    })

    def fake_run(cmd, **kw):
        target = Path(cmd[3])
        (target / ".git").mkdir(parents=True)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(repo_map.subprocess, "run", fake_run)
    rc, out, err = _run(monkeypatch, capsys, [UUID_A, "--mapping-path", str(map_path)])
    assert rc == 0
    assert "Cloned into" in err
    assert "alpha" in out


def test_resolve_no_clone_exits_2(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(repo_map, "stellar_engine_parent", lambda: tmp_path)
    map_path = _write_map(tmp_path, {
        UUID_A: {"repo_name": "alpha", "git_url": "x", "workspace_prefix": "A"},
    })
    rc, out, err = _run(monkeypatch, capsys, [UUID_A, "--no-clone", "--mapping-path", str(map_path)])
    assert rc == 2
    assert "missing locally" in err.lower() or "no-clone" in err.lower()


def test_resolve_clone_failure_exits_3_with_git_stderr(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(repo_map, "stellar_engine_parent", lambda: tmp_path)
    map_path = _write_map(tmp_path, {
        UUID_A: {"repo_name": "alpha", "git_url": "git@x:bad.git", "workspace_prefix": "A"},
    })

    def boom(cmd, **kw):
        raise subprocess.CalledProcessError(
            returncode=128, cmd=cmd, stderr="Permission denied (publickey)."
        )

    monkeypatch.setattr(repo_map.subprocess, "run", boom)
    rc, out, err = _run(monkeypatch, capsys, [UUID_A, "--mapping-path", str(map_path)])
    assert rc == 3
    assert "Permission denied" in err


def test_resolve_target_repo_skips_clone(monkeypatch, tmp_path, capsys):
    override = tmp_path / "elsewhere"
    override.mkdir()
    map_path = _write_map(tmp_path, {})
    rc, out, err = _run(monkeypatch, capsys, [
        UUID_A, "--target-repo", str(override), "--mapping-path", str(map_path),
    ])
    assert rc == 0
    assert out.strip() == str(override.resolve())


def test_resolve_unmapped_exits_1(monkeypatch, tmp_path, capsys):
    map_path = _write_map(tmp_path, {})
    rc, out, err = _run(monkeypatch, capsys, [UUID_A, "--mapping-path", str(map_path)])
    assert rc == 1
    assert UUID_A in err
