#!/usr/bin/env python3
"""
QA Phase 0: Resolve and load the QA checklist for an issue.

Resolution order (first match wins):
  1. --checklist <path>  (explicit)
  2. --type cli|api|web|mobile → bundled template
  3. grava wisp read <id> qa_checklist (if non-empty)
  4. <target-repo>/docs/qa/default-checklist.md
  5. agents/orchestrator/templates/qa/default-checklist.md (bundled fallback)

Usage: python3 qa_load.py <id> [--target-repo <path>]
                           [--checklist <path>] [--type cli|api|web|mobile]
                           [--out <path>]
Output: JSON {id, checklist_path, source, out}
Exit codes:
  0 = ok
  1 = no checklist found at any source
  2 = read/write error
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

TYPE_TEMPLATES = {
    "cli":    "cli-checklist.md",
    "api":    "api-checklist.md",
    "web":    "web-checklist.md",
    "mobile": "mobile-checklist.md",
}


def find_stellar_root(start: Path) -> Path:
    current = start.resolve()
    while current != current.parent:
        if (current / "repo-map.yaml").exists():
            return current
        current = current.parent
    raise FileNotFoundError(f"repo-map.yaml not found walking up from {start}")


def wisp_read(issue_id: str, key: str, cwd: str) -> str:
    r = subprocess.run(
        ["grava", "wisp", "read", issue_id, key],
        capture_output=True, text=True, cwd=cwd,
    )
    return r.stdout.strip() if r.returncode == 0 else ""


def wisp_write(issue_id: str, key: str, value: str, cwd: str) -> None:
    subprocess.run(
        ["grava", "wisp", "write", issue_id, key, value],
        capture_output=True, cwd=cwd,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("id", help="Grava issue ID")
    parser.add_argument("--target-repo", default=".")
    parser.add_argument("--checklist", default=None)
    parser.add_argument("--type", choices=["cli", "api", "web", "mobile"], default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    cwd = args.target_repo
    out_path = args.out or os.path.join(cwd, ".grava", f"qa-{args.id}-checklist.md")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    # Find bundled templates dir
    try:
        stellar_root = find_stellar_root(Path(__file__).parent)
        templates_dir = stellar_root / "agents" / "orchestrator" / "templates" / "qa"
    except FileNotFoundError:
        templates_dir = None

    resolved_path: str | None = None
    source: str = ""

    # 1. --checklist
    if args.checklist:
        resolved_path = args.checklist
        source = "explicit"

    # 2. --type → bundled template
    if not resolved_path and args.type:
        if templates_dir:
            candidate = templates_dir / TYPE_TEMPLATES[args.type]
            if candidate.exists():
                resolved_path = str(candidate)
                source = f"type:{args.type}"

    # 3. Wisp qa_checklist
    if not resolved_path:
        wisp_val = wisp_read(args.id, "qa_checklist", cwd)
        if wisp_val and Path(wisp_val).exists():
            resolved_path = wisp_val
            source = "wisp"

    # 4. Repo default
    if not resolved_path:
        candidate = os.path.join(cwd, "docs", "qa", "default-checklist.md")
        if os.path.exists(candidate):
            resolved_path = candidate
            source = "repo-default"

    # 5. Bundled default
    if not resolved_path and templates_dir:
        candidate = templates_dir / "default-checklist.md"
        if candidate.exists():
            resolved_path = str(candidate)
            source = "bundled-default"

    if not resolved_path:
        print("ERROR: no checklist found at any source", file=sys.stderr)
        sys.exit(1)

    # Read content
    try:
        content = Path(resolved_path).read_text()
    except OSError as exc:
        print(f"ERROR: cannot read checklist '{resolved_path}': {exc}", file=sys.stderr)
        sys.exit(2)

    # Atomic write to out
    try:
        tmp = out_path + ".tmp"
        Path(tmp).write_text(content)
        os.replace(tmp, out_path)
    except OSError as exc:
        print(f"ERROR: cannot write checklist to '{out_path}': {exc}", file=sys.stderr)
        sys.exit(2)

    wisp_write(args.id, "qa_checklist", resolved_path, cwd)

    print(json.dumps({
        "id": args.id,
        "checklist_path": resolved_path,
        "source": source,
        "out": out_path,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
