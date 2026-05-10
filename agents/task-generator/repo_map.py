"""Plane project UUID -> sibling repo path resolver, with auto-clone."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_MAPPING_PATH = Path(__file__).resolve().parent.parent.parent / "repo-map.yaml"

# Per-system config layout: each `systems/<Name>/system.yaml` holds one or
# more `projects:` entries that get merged on top of the root mapping.
SYSTEMS_DIR = Path(__file__).resolve().parent.parent.parent / "systems"
SYSTEM_CONFIG_FILENAME = "system.yaml"


class RepoMapError(Exception):
    pass


@dataclass
class RepoMapEntry:
    repo_name: str
    git_url: str
    workspace_prefix: str


@dataclass
class RepoMapping:
    repo: Path
    workspace_prefix: str
    cloned: bool


def stellar_engine_parent() -> Path:
    """Return the directory that contains stellar-engine (siblings live here)."""
    return Path(__file__).resolve().parent.parent.parent.parent


def _entries_from_yaml(yaml_path: Path) -> dict[str, RepoMapEntry]:
    if not yaml_path.exists():
        return {}
    raw = yaml.safe_load(yaml_path.read_text()) or {}
    projects = raw.get("projects", {}) or {}
    out: dict[str, RepoMapEntry] = {}
    for project_id, entry in projects.items():
        if not isinstance(entry, dict):
            continue
        out[str(project_id)] = RepoMapEntry(
            repo_name=str(entry.get("repo_name", "")),
            git_url=str(entry.get("git_url", "")),
            workspace_prefix=str(entry.get("workspace_prefix", "STELLAR")),
        )
    return out


def discover_system_configs(systems_dir: Path | None = None) -> dict[str, RepoMapEntry]:
    """Walk `systems/*/system.yaml` and merge their `projects:` entries.

    Per-system entries override root `repo-map.yaml` entries on conflict.
    """
    base = systems_dir or SYSTEMS_DIR
    if not base.exists():
        return {}
    out: dict[str, RepoMapEntry] = {}
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        cfg = child / SYSTEM_CONFIG_FILENAME
        if not cfg.exists():
            continue
        out.update(_entries_from_yaml(cfg))
    return out


def load_repo_map(path: Path | None = None) -> dict[str, RepoMapEntry]:
    """Load merged Plane project → repo mapping.

    Sources, in order (later wins on conflict):
      1. Root `repo-map.yaml` (or `path` override)
      2. Each `systems/<Name>/system.yaml`
    """
    mapping_path = path or DEFAULT_MAPPING_PATH
    out = _entries_from_yaml(mapping_path)
    out.update(discover_system_configs())
    return out


def lookup_project(
    project_id: str,
    override_repo: Path | None = None,
    mapping_path: Path | None = None,
    allow_clone: bool = True,
) -> RepoMapping:
    if override_repo is not None:
        entries = load_repo_map(mapping_path)
        prefix = entries[project_id].workspace_prefix if project_id in entries else "STELLAR"
        return RepoMapping(repo=Path(override_repo).resolve(), workspace_prefix=prefix, cloned=False)

    entries = load_repo_map(mapping_path)
    if project_id not in entries:
        path = mapping_path or DEFAULT_MAPPING_PATH
        raise KeyError(
            f"Plane project {project_id!r} is not mapped in {path}. "
            f"Add an entry under 'projects:' or pass --target-repo to override."
        )
    entry = entries[project_id]
    if not entry.repo_name:
        raise RepoMapError(f"Mapping for {project_id} is missing 'repo_name'.")

    target = stellar_engine_parent() / entry.repo_name

    if target.exists():
        if not (target / ".git").exists():
            raise RepoMapError(
                f"Folder {target} exists but is not a git repo. "
                f"Move or delete it, then re-run (the agent will clone fresh)."
            )
        return RepoMapping(repo=target, workspace_prefix=entry.workspace_prefix, cloned=False)

    if not allow_clone:
        raise RepoMapError(
            f"Repo {target} missing locally and --no-clone was set. "
            f"Drop --no-clone, pre-clone manually, or pass --target-repo PATH."
        )

    if not entry.git_url:
        raise RepoMapError(
            f"Mapping for {project_id} is missing 'git_url'; cannot clone {target}."
        )

    try:
        subprocess.run(
            ["git", "clone", entry.git_url, str(target)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise RepoMapError(
            f"git clone {entry.git_url} into {target} failed:\n{e.stderr.strip()}"
        ) from e

    return RepoMapping(repo=target, workspace_prefix=entry.workspace_prefix, cloned=True)
