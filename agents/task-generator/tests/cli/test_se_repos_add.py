"""Tests for `se repos add` subcommand.

Subprocess-based: shells out to the actual `cli/se` script to verify the
full argparse wiring + handler flow. Uses tmp_path so no real repos.yaml
is touched.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

# tests/cli/test_se_repos_add.py → parents[4] = repo root
REPO_ROOT = Path(__file__).resolve().parents[4]
SE = REPO_ROOT / "cli" / "se"


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SE), *args],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(cwd) if cwd else None,
    )


def _make_grava_dir(tmp: Path, name: str) -> Path:
    """Create <tmp>/<name>/.grava/ so `grava init` is skipped."""
    repo = tmp / name
    (repo / ".grava").mkdir(parents=True)
    return repo


def test_help_works() -> None:
    r = _run(["repos", "add", "--help"])
    assert r.returncode == 0, r.stderr
    assert "--path" in r.stdout
    assert "name" in r.stdout
    assert "--no-init" in r.stdout
    assert "--force" in r.stdout


def test_listed_in_repos_help() -> None:
    r = _run(["repos", "--help"])
    assert r.returncode == 0, r.stderr
    assert "add" in r.stdout
    assert "list" in r.stdout


def test_missing_required_path_fails() -> None:
    r = _run(["repos", "add", "myrepo"])
    assert r.returncode != 0
    assert "--path" in (r.stderr + r.stdout)


def test_add_basic(tmp_path: Path) -> None:
    repo = _make_grava_dir(tmp_path, "grava")
    cfg = tmp_path / "engine"
    r = _run(["repos", "add", "grava", "--path", str(repo), "--dir", str(cfg)])
    assert r.returncode == 0, r.stderr

    content = (cfg / "repos.yaml").read_text()
    assert "# repos.yaml" in content  # header preserved
    assert "# Distinct from repo-map.yaml" in content
    assert "# Example:" not in content  # example block dropped

    data = yaml.safe_load(content)
    assert "grava" in data["repos"]
    assert data["repos"]["grava"]["path"] == str(repo)
    assert data["repos"]["grava"]["max_concurrent"] == 2
    assert data["repos"]["grava"]["priority_threshold"] == "medium"
    assert data["repos"]["grava"]["poll_interval"] == 60


def test_add_with_overrides(tmp_path: Path) -> None:
    repo = _make_grava_dir(tmp_path, "repo2")
    cfg = tmp_path / "engine"
    r = _run([
        "repos", "add", "repo2", "--path", str(repo),
        "--max-concurrent", "5",
        "--priority-threshold", "high",
        "--poll-interval", "15",
        "--dir", str(cfg),
    ])
    assert r.returncode == 0, r.stderr
    data = yaml.safe_load((cfg / "repos.yaml").read_text())
    assert data["repos"]["repo2"]["max_concurrent"] == 5
    assert data["repos"]["repo2"]["priority_threshold"] == "high"
    assert data["repos"]["repo2"]["poll_interval"] == 15


def test_add_two_repos_preserves_existing(tmp_path: Path) -> None:
    cfg = tmp_path / "engine"
    repo_a = _make_grava_dir(tmp_path, "a")
    repo_b = _make_grava_dir(tmp_path, "b")
    _run(["repos", "add", "a", "--path", str(repo_a), "--dir", str(cfg)])
    _run(["repos", "add", "b", "--path", str(repo_b), "--dir", str(cfg)])
    data = yaml.safe_load((cfg / "repos.yaml").read_text())
    assert set(data["repos"].keys()) == {"a", "b"}


def test_duplicate_rejected_without_force(tmp_path: Path) -> None:
    repo = _make_grava_dir(tmp_path, "dup")
    cfg = tmp_path / "engine"
    r1 = _run(["repos", "add", "dup", "--path", str(repo), "--dir", str(cfg)])
    assert r1.returncode == 0, r1.stderr
    r2 = _run(["repos", "add", "dup", "--path", str(repo), "--dir", str(cfg)])
    assert r2.returncode == 1
    assert "already" in r2.stderr.lower()


def test_duplicate_force_overwrites(tmp_path: Path) -> None:
    repo_a = _make_grava_dir(tmp_path, "a")
    repo_b = _make_grava_dir(tmp_path, "b")
    cfg = tmp_path / "engine"
    _run(["repos", "add", "x", "--path", str(repo_a), "--dir", str(cfg)])
    r = _run([
        "repos", "add", "x", "--path", str(repo_b),
        "--force", "--dir", str(cfg),
    ])
    assert r.returncode == 0, r.stderr
    data = yaml.safe_load((cfg / "repos.yaml").read_text())
    assert data["repos"]["x"]["path"] == str(repo_b)


def test_missing_path_rejected(tmp_path: Path) -> None:
    cfg = tmp_path / "engine"
    r = _run([
        "repos", "add", "ghost",
        "--path", str(tmp_path / "does-not-exist"),
        "--dir", str(cfg),
    ])
    assert r.returncode == 1
    assert "does not exist" in r.stderr


def test_path_must_be_directory(tmp_path: Path) -> None:
    cfg = tmp_path / "engine"
    f = tmp_path / "file.txt"
    f.write_text("not a dir")
    r = _run(["repos", "add", "bad", "--path", str(f), "--dir", str(cfg)])
    assert r.returncode == 1
    assert "not a directory" in r.stderr


def test_no_init_skips_grava(tmp_path: Path) -> None:
    """--no-init with a fresh dir should succeed without creating .grava/."""
    repo = tmp_path / "fresh"
    repo.mkdir()
    cfg = tmp_path / "engine"
    r = _run([
        "repos", "add", "fresh", "--path", str(repo),
        "--no-init", "--dir", str(cfg),
    ])
    assert r.returncode == 0, r.stderr
    assert not (repo / ".grava").exists()
    assert "skipped" in r.stdout


def test_bare_repos_still_lists(tmp_path: Path) -> None:
    """Backward compat — `se repos` (no action) lists without erroring."""
    cfg = tmp_path / "engine"
    cfg.mkdir()
    r = _run(["repos"], cwd=cfg)
    assert r.returncode == 0, r.stderr
    assert "No repos configured" in r.stdout


def test_list_subcommand_after_add(tmp_path: Path) -> None:
    """`se repos list` shows what `se repos add` wrote."""
    repo = _make_grava_dir(tmp_path, "listed")
    cfg = tmp_path / "engine"
    _run(["repos", "add", "listed", "--path", str(repo), "--dir", str(cfg)])
    r = _run(["repos", "list", "--dir", str(cfg)])
    assert r.returncode == 0, r.stderr
    assert "listed" in r.stdout
    assert str(repo) in r.stdout


def test_list_json_after_add(tmp_path: Path) -> None:
    import json
    repo = _make_grava_dir(tmp_path, "jrepo")
    cfg = tmp_path / "engine"
    _run(["repos", "add", "jrepo", "--path", str(repo), "--dir", str(cfg)])
    r = _run(["repos", "list", "--json", "--dir", str(cfg)])
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert "jrepo" in data
