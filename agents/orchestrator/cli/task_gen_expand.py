#!/usr/bin/env python3
"""
Bridge: resolve page_id from a grava epic issue, then delegate to task-generator.

A grava epic created by task-generator carries a `tg:src:<page_id>` label.
This script extracts that page_id, looks up the Plane project_id, then delegates
to agents/task-generator/cli/run.py.

Usage: python3 task_gen_expand.py <epic-id> [--target-repo <path>] [--dry-run]
Output: JSON {epic_id, page_id, project_id, task_gen_exit_code}
Exit codes:
  0 = ok (or --dry-run complete)
  1 = cannot resolve page_id or project_id
  2 = operator declined
  pass-through: task-generator exit codes (5=partial, 6=rollback, 7=dep cycle)

Algorithm:
  1. grava show <epic-id> --json → parse labels list
  2. Extract page_id from "tg:src:<page_id>" label; exit 1 if absent
  3. Resolve project_id:
     a. grava wisp read <epic-id> plane_project_id  (prefer explicit wisp)
     b. Walk up from __file__ to find stellar_root (repo-map.yaml present)
        Read repo-map.yaml + systems/*/system.yaml projects dicts
        Match target_repo basename/realpath → project UUID
     c. Exit 1 with guidance if still unresolved
  4. Print: "Found Plane spec: project=<id> page=<id>" + proposed command
  5. If NOT --dry-run: prompt operator "Proceed? [yes/no]"; exit 2 if declined
  6. Delegate: python3 agents/task-generator/cli/run.py <project_id> <page_id>
               [--dry-run] [--target-repo <path>]
     Surface stdout/stderr unchanged (task-generator manages its own approval gate)
  7. Print JSON {epic_id, page_id, project_id, task_gen_exit_code}
  8. Return task-generator's exit code (5/6/7 pass through)

Note: two approval gates exist — this script's gate (step 5) and task-generator's
own gate (before Phase B Plane writes). Both must be cleared.
"""
import argparse
import json
import os
import subprocess
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


def extract_page_id(labels: list[str]) -> str:
    for lb in labels:
        if lb.startswith("tg:src:"):
            return lb[len("tg:src:"):]
    return ""


def _load_projects_from_yaml(yaml_path: Path) -> dict[str, dict]:
    """Load projects dict from a repo-map.yaml or system.yaml file.
    Returns {project_uuid: {repo_name, git_url, ...}} or {} on error.
    """
    if not yaml_path.exists():
        return {}
    text = yaml_path.read_text()
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text) or {}
    except ImportError:
        # Minimal manual parse: extract "uuid": section keys
        data = {}
        current_uuid = ""
        current_block: dict = {}
        for line in text.splitlines():
            # Match top-level UUID key: `  "uuid":` or `  uuid:`
            stripped = line.strip()
            import re as _re
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


def resolve_project_id_from_map(target_repo: str, stellar_root: Path) -> str:
    """Match target_repo by repo_name against all projects in repo-map.yaml
    and systems/*/system.yaml.  Returns project UUID or empty string.
    """
    target_name = os.path.basename(os.path.realpath(target_repo))
    target_abs = os.path.realpath(target_repo)
    # Sibling repos live next to stellar-engine/
    parent = stellar_root.parent

    all_projects: dict[str, dict] = {}

    # Root repo-map.yaml
    all_projects.update(_load_projects_from_yaml(stellar_root / "repo-map.yaml"))

    # Per-system system.yaml files (win on conflict)
    for sys_yaml in sorted((stellar_root / "systems").glob("*/system.yaml")):
        all_projects.update(_load_projects_from_yaml(sys_yaml))

    for uuid, entry in all_projects.items():
        repo_name = entry.get("repo_name", "")
        if not repo_name:
            continue
        candidate = os.path.realpath(str(parent / repo_name))
        if candidate == target_abs or repo_name == target_name:
            return uuid

    return ""


def wisp_read(issue_id: str, key: str, cwd: str) -> str:
    r = subprocess.run(
        ["grava", "wisp", "read", issue_id, key],
        capture_output=True, text=True, cwd=cwd,
    )
    return r.stdout.strip() if r.returncode == 0 else ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("epic_id", help="Grava epic issue ID")
    parser.add_argument("--target-repo", default=".")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run task-generator Phase A preview only; skip approval gate")
    args = parser.parse_args(argv)

    cwd = args.target_repo

    # 1. Fetch epic
    r = subprocess.run(
        ["grava", "show", args.epic_id, "--json"],
        capture_output=True, text=True, cwd=cwd,
    )
    if r.returncode != 0:
        print(f"ERROR: issue not found: {args.epic_id}", file=sys.stderr)
        sys.exit(1)

    try:
        issue = json.loads(r.stdout)
    except json.JSONDecodeError as exc:
        print(f"ERROR: bad JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    labels = [str(lb) for lb in (issue.get("labels") or [])]

    # 2. Extract page_id
    page_id = extract_page_id(labels)
    if not page_id:
        print(
            f"ERROR: no 'tg:src:<page_id>' label on {args.epic_id}.\n"
            f"Labels found: {labels}\n"
            f"Epic was not created by task-generator, or label was removed.",
            file=sys.stderr,
        )
        sys.exit(1)

    # 3. Resolve project_id: try wisp first, then repo-map.yaml
    project_id = wisp_read(args.epic_id, "plane_project_id", cwd)

    if not project_id:
        try:
            stellar_root = find_stellar_root(Path(__file__).parent)
            project_id = resolve_project_id_from_map(cwd, stellar_root)
        except FileNotFoundError:
            pass

    if not project_id:
        print(
            f"ERROR: cannot resolve project_id for repo '{cwd}'.\n"
            f"Fix options:\n"
            f"  1. Add entry to repo-map.yaml\n"
            f"  2. grava wisp write {args.epic_id} plane_project_id <uuid>",
            file=sys.stderr,
        )
        sys.exit(1)

    # 4. Build task-generator command
    stellar_root = find_stellar_root(Path(__file__).parent)
    task_gen_run = stellar_root / "agents" / "task-generator" / "cli" / "run.py"

    cmd = [
        sys.executable, str(task_gen_run),
        project_id, page_id,
        "--target-repo", cwd,
    ]
    if args.dry_run:
        cmd.append("--dry-run")

    print(f"Found Plane spec:  project={project_id}  page={page_id}")
    print(f"Will run: {' '.join(cmd)}")

    # 5. Approval gate (skip for --dry-run)
    if not args.dry_run:
        print(
            "\nThis will delegate to task-generator (Phase A preview only initially).\n"
            "task-generator will ask for approval again before Plane writes (Phase B)\n"
            "and again before Grava mirror (Phase C)."
        )
        try:
            answer = input("Proceed? [yes/no]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer not in ("yes", "y"):
            print("Declined.", file=sys.stderr)
            sys.exit(2)

    # 6. Delegate to task-generator
    result = subprocess.run(cmd)
    task_gen_exit = result.returncode

    print(json.dumps({
        "epic_id": args.epic_id,
        "page_id": page_id,
        "project_id": project_id,
        "task_gen_exit_code": task_gen_exit,
    }))
    return task_gen_exit


if __name__ == "__main__":
    sys.exit(main())
