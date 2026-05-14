#!/usr/bin/env python3
"""
Route a grava issue to the correct team.

Usage: python3 route.py <id> [--target-repo <path>]
Output: JSON {"id": ..., "team": ..., "type": ..., "labels": [...]}
Exit codes:
  0 = routed successfully
  1 = unroutable type or issue not found
  2 = grava command failed
"""
import argparse
import json
import subprocess
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Route a grava issue to the correct team.")
    parser.add_argument("id", help="Grava issue ID")
    parser.add_argument("--target-repo", default=".", help="Path to grava-initialised repo")
    args = parser.parse_args()

    # Fetch issue
    r = subprocess.run(
        ["grava", "show", args.id, "--json"],
        capture_output=True, text=True, cwd=args.target_repo,
    )
    if r.returncode != 0:
        err = r.stderr.strip()
        print(f"ERROR: grava show failed: {err}", file=sys.stderr)
        sys.exit(1 if "not found" in err.lower() else 2)

    try:
        issue = json.loads(r.stdout)
    except json.JSONDecodeError as exc:
        print(f"ERROR: bad JSON from grava show: {exc}", file=sys.stderr)
        sys.exit(2)

    issue_type = (issue.get("type") or "").lower()
    labels = [str(lb) for lb in (issue.get("labels") or [])]

    # Routing (label check before type — qa-ready overrides type)
    if "qa-ready" in labels:
        team = "qa"
    elif issue_type == "bug":
        team = "fix-bug"
    elif issue_type in ("task", "story", "subtask"):
        team = "epic-task"
    elif issue_type == "epic":
        team = "task-generator"
    else:
        print(f"ERROR: unroutable type '{issue_type}' for {args.id}", file=sys.stderr)
        sys.exit(1)

    # Write team wisp (best-effort; don't fail if grava wisp write fails)
    subprocess.run(
        ["grava", "wisp", "write", args.id, "team", team],
        capture_output=True, cwd=args.target_repo,
    )

    print(json.dumps({"id": args.id, "team": team, "type": issue_type, "labels": labels}))


if __name__ == "__main__":
    main()
