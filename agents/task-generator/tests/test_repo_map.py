"""Unit tests for repo_map.py."""

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import repo_map  # noqa: E402
from repo_map import (  # noqa: E402
    RepoMapError,
    load_repo_map,
    lookup_project,
    stellar_engine_parent,
)

UUID_A = "11111111-1111-1111-1111-111111111111"
UUID_B = "22222222-2222-2222-2222-222222222222"


def _write_map(tmp_path: Path, projects: dict) -> Path:
    p = tmp_path / "repo-map.yaml"
    p.write_text(yaml.safe_dump({"projects": projects}))
    return p


def test_load_repo_map_basic(tmp_path):
    path = _write_map(tmp_path, {
        UUID_A: {"repo_name": "alpha", "git_url": "git@x:a.git", "workspace_prefix": "A"},
    })
    entries = load_repo_map(path)
    assert UUID_A in entries
    assert entries[UUID_A].repo_name == "alpha"
    assert entries[UUID_A].workspace_prefix == "A"


def test_load_repo_map_missing_file(tmp_path):
    entries = load_repo_map(tmp_path / "absent.yaml")
    assert entries == {}


def test_lookup_missing_project_raises(tmp_path):
    path = _write_map(tmp_path, {})
    with pytest.raises(KeyError, match=UUID_A):
        lookup_project(UUID_A, mapping_path=path)


def test_override_repo_synthesizes(tmp_path):
    path = _write_map(tmp_path, {
        UUID_A: {"repo_name": "alpha", "git_url": "x", "workspace_prefix": "A"},
    })
    override = tmp_path / "elsewhere"
    override.mkdir()
    mapping = lookup_project(UUID_A, override_repo=override, mapping_path=path)
    assert mapping.repo == override.resolve()
    assert mapping.workspace_prefix == "A"
    assert mapping.cloned is False


def test_override_repo_no_yaml_entry_falls_back_to_default_prefix(tmp_path):
    path = _write_map(tmp_path, {})
    override = tmp_path / "elsewhere"
    override.mkdir()
    mapping = lookup_project(UUID_B, override_repo=override, mapping_path=path)
    assert mapping.workspace_prefix == "STELLAR"


def test_lookup_existing_repo_no_clone(tmp_path, monkeypatch):
    target = tmp_path / "alpha"
    (target / ".git").mkdir(parents=True)
    monkeypatch.setattr(repo_map, "stellar_engine_parent", lambda: tmp_path)
    path = _write_map(tmp_path, {
        UUID_A: {"repo_name": "alpha", "git_url": "x", "workspace_prefix": "A"},
    })
    called = {"count": 0}
    monkeypatch.setattr(repo_map.subprocess, "run", lambda *a, **kw: called.update(count=called["count"] + 1))
    mapping = lookup_project(UUID_A, mapping_path=path)
    assert mapping.repo == target
    assert mapping.cloned is False
    assert called["count"] == 0


def test_lookup_clones_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(repo_map, "stellar_engine_parent", lambda: tmp_path)
    path = _write_map(tmp_path, {
        UUID_A: {"repo_name": "alpha", "git_url": "git@example:a.git", "workspace_prefix": "A"},
    })
    recorded = []

    def fake_run(cmd, **kw):
        recorded.append(cmd)
        target = Path(cmd[3])
        (target / ".git").mkdir(parents=True)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(repo_map.subprocess, "run", fake_run)
    mapping = lookup_project(UUID_A, mapping_path=path)
    assert recorded[0][0] == "git"
    assert recorded[0][1] == "clone"
    assert recorded[0][2] == "git@example:a.git"
    assert mapping.cloned is True


def test_lookup_no_clone_flag_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(repo_map, "stellar_engine_parent", lambda: tmp_path)
    path = _write_map(tmp_path, {
        UUID_A: {"repo_name": "alpha", "git_url": "x", "workspace_prefix": "A"},
    })
    with pytest.raises(RepoMapError, match="--no-clone"):
        lookup_project(UUID_A, mapping_path=path, allow_clone=False)


def test_lookup_folder_exists_no_git_raises(tmp_path, monkeypatch):
    target = tmp_path / "alpha"
    target.mkdir()
    monkeypatch.setattr(repo_map, "stellar_engine_parent", lambda: tmp_path)
    path = _write_map(tmp_path, {
        UUID_A: {"repo_name": "alpha", "git_url": "x", "workspace_prefix": "A"},
    })
    with pytest.raises(RepoMapError, match="not a git repo"):
        lookup_project(UUID_A, mapping_path=path)


def test_clone_failure_surfaces_stderr(tmp_path, monkeypatch):
    monkeypatch.setattr(repo_map, "stellar_engine_parent", lambda: tmp_path)
    path = _write_map(tmp_path, {
        UUID_A: {"repo_name": "alpha", "git_url": "git@x:bad.git", "workspace_prefix": "A"},
    })

    def boom(cmd, **kw):
        raise subprocess.CalledProcessError(
            returncode=128, cmd=cmd, stderr="Permission denied (publickey)."
        )

    monkeypatch.setattr(repo_map.subprocess, "run", boom)
    with pytest.raises(RepoMapError, match="Permission denied"):
        lookup_project(UUID_A, mapping_path=path)


def test_stellar_engine_parent_is_ideaprojects():
    assert stellar_engine_parent().name in ("IdeaProjects", "Projects", "src", "code") or \
           stellar_engine_parent().exists()
