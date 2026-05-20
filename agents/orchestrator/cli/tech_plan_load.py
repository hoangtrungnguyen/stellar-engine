#!/usr/bin/env python3
"""
Resolve the tech plan for the current session's target repo.

The tech plan is a free-form markdown file describing the project's technical scope,
constraints, and goals for the current development phase. No fixed format is required —
the agent reads it as prose and applies judgment. It lives at:
  systems/<Name>/tech-plan.md  (alongside system.yaml inside stellar-engine)

Load it ONCE at the start of an orchestrator session for the task-generator team.
Do NOT call this per-issue — it is a session-level context document.

Usage: python3 tech_plan_load.py [--target-repo <path>] [--system <Name>]
Output: JSON {system_name, tech_plan_path (absolute), exists}
        (agent should then call Read(tech_plan_path) to load content into context)
Exit codes:
  0 = resolved and file exists
  1 = system not found or tech-plan.md missing

Algorithm:
  1. Walk up from this file's directory until repo-map.yaml is found → stellar_root
  2. Resolve system name:
     a. --system <Name> if provided → use directly
     b. Else: read systems/*/system.yaml files looking for tech_plan_path key or
        repo_name matching target_repo basename / realpath
     c. Else: walk repo-map.yaml projects dict → match target_repo basename → system dir name
  3. tech_plan_path = stellar_root / "systems" / <Name> / "tech-plan.md"
  4. If file not found → exit 1 with guidance on how to create it
  5. Print JSON: {system_name, tech_plan_path, exists: true}
     (script does NOT print file content — agent's Read tool handles that)
"""
import argparse
import json
import os
import sys
from pathlib import Path


def find_stellar_root(start: Path) -> Path:
    """Walk up from start until repo-map.yaml found."""
    current = start.resolve()
    while current != current.parent:
        if (current / "repo-map.yaml").exists():
            return current
        current = current.parent
    raise FileNotFoundError(f"repo-map.yaml not found walking up from {start}")


def _load_yaml_safe(yaml_path: Path) -> dict:
    """Load a YAML file, returning {} on error. Uses PyYAML if available."""
    if not yaml_path.exists():
        return {}
    text = yaml_path.read_text()
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text) or {}
    except ImportError:
        pass
    # Minimal fallback: only reads top-level key: value pairs (good enough for system.yaml)
    result: dict = {}
    for line in text.splitlines():
        if ":" in line and not line.startswith(" ") and not line.startswith("#"):
            k, _, v = line.partition(":")
            result[k.strip().strip("\"'")] = v.strip().strip("\"'")
    return result


def _load_projects_from_yaml(yaml_path: Path) -> dict[str, dict]:
    """Load {uuid: {repo_name, ...}} from a repo-map.yaml or system.yaml."""
    if not yaml_path.exists():
        return {}
    text = yaml_path.read_text()
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text) or {}
    except ImportError:
        data = {}
        current_uuid = ""
        current_block: dict = {}
        import re as _re
        for line in text.splitlines():
            stripped = line.strip()
            m = _re.match(r'^"?([0-9a-f\-]{36})"?\s*:', stripped)
            if m and not line.startswith(" " * 6):
                if current_uuid:
                    data.setdefault("projects", {})[current_uuid] = current_block
                current_uuid = m.group(1)
                current_block = {}
            elif current_uuid and ":" in stripped:
                k, _, v = stripped.partition(":")
                current_block[k.strip().strip("\"'")] = v.strip().strip("\"'")
        if current_uuid:
            data.setdefault("projects", {})[current_uuid] = current_block
    return data.get("projects") or {}


def resolve_system_name(target_repo: str, stellar_root: Path) -> str:
    """
    Match target_repo to a system directory under stellar_root/systems/.

    Resolution order:
      1. systems/*/system.yaml with matching repo_name (from projects dict)
      2. Basename of target_repo matched against systems/ directory names
    Returns system directory name (e.g. "SportBuddies") or "".
    """
    target_name = os.path.basename(os.path.realpath(target_repo))
    target_abs = os.path.realpath(target_repo)
    parent = stellar_root.parent

    systems_dir = stellar_root / "systems"
    if not systems_dir.is_dir():
        return ""

    # Check each system's system.yaml for matching repo_name in projects
    for sys_dir in sorted(systems_dir.iterdir()):
        if not sys_dir.is_dir():
            continue
        sys_yaml = sys_dir / "system.yaml"
        projects = _load_projects_from_yaml(sys_yaml)
        for _uuid, entry in projects.items():
            repo_name = entry.get("repo_name", "")
            if not repo_name:
                continue
            candidate = os.path.realpath(str(parent / repo_name))
            if candidate == target_abs or repo_name == target_name:
                return sys_dir.name

    # Fallback: match systems/<Name> directory against target_repo basename
    for sys_dir in sorted(systems_dir.iterdir()):
        if sys_dir.is_dir() and sys_dir.name == target_name:
            return sys_dir.name

    # Also check root repo-map.yaml
    root_projects = _load_projects_from_yaml(stellar_root / "repo-map.yaml")
    for _uuid, entry in root_projects.items():
        repo_name = entry.get("repo_name", "")
        if not repo_name:
            continue
        candidate = os.path.realpath(str(parent / repo_name))
        if candidate == target_abs or repo_name == target_name:
            # Found in root repo-map; try to find matching system dir by repo_name
            for sys_dir in sorted(systems_dir.iterdir()):
                if sys_dir.is_dir() and (
                    sys_dir.name == repo_name or sys_dir.name == target_name
                ):
                    return sys_dir.name

    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Resolve the tech plan file for the current project."
    )
    parser.add_argument("--target-repo", default=".", help="Path to the target repository")
    parser.add_argument(
        "--system", default="",
        help="Override system name (directory under systems/) instead of auto-resolving"
    )
    args = parser.parse_args(argv)

    # 1. Find stellar root
    try:
        stellar_root = find_stellar_root(Path(__file__).parent)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # 2. Resolve system name
    system_name = args.system.strip()
    if not system_name:
        system_name = resolve_system_name(args.target_repo, stellar_root)

    if not system_name:
        target_abs = os.path.realpath(args.target_repo)
        print(
            f"ERROR: cannot resolve system name for target-repo '{target_abs}'.\n"
            f"Fix options:\n"
            f"  1. Add repo_name entry to systems/<Name>/system.yaml or repo-map.yaml\n"
            f"  2. Use --system <Name> to specify the system directory explicitly\n"
            f"     (directory must exist under {stellar_root / 'systems'})",
            file=sys.stderr,
        )
        sys.exit(1)

    # 3. Build tech plan path
    tech_plan_path = stellar_root / "systems" / system_name / "tech-plan.md"

    # 4. Check existence
    if not tech_plan_path.exists():
        print(
            f"ERROR: tech-plan.md not found at {tech_plan_path}.\n"
            f"\n"
            f"Create a markdown file at that path describing the project's technical plan.\n"
            f"No fixed format is required — the agent reads the document as free-form text\n"
            f"and uses its content to understand technical scope and constraints.\n"
            f"\n"
            f"Suggested content to include:\n"
            f"  - Technical goals or features for the current phase\n"
            f"  - Areas explicitly excluded or deferred (helps the agent skip out-of-scope epics)\n"
            f"  - Architecture decisions, constraints, or dependencies\n"
            f"  - Epic/story breakdown if available",
            file=sys.stderr,
        )
        sys.exit(1)

    # 5. Print JSON (agent reads file via Read tool)
    print(json.dumps({
        "system_name": system_name,
        "tech_plan_path": str(tech_plan_path.resolve()),
        "exists": True,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
