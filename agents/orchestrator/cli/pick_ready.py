#!/usr/bin/env python3
"""
Pick the next ready issue(s) for a given team from the grava backlog.

Usage: python3 pick_ready.py --team fix-bug|epic-task|qa|task-generator
                              [--limit N] [--target-repo <path>]
Output: JSON array [{id, title, type}]  (may be [])
Exit codes:
  0 = ok (empty array is valid)
  1 = grava command failed
"""
import argparse
import json
import subprocess
import sys

TERMINAL_PHASES = {"", "complete", "failed"}

TYPE_FILTER: dict[str, set[str]] = {
    "fix-bug":        {"bug"},
    "epic-task":      {"task", "story", "subtask"},
    "task-generator": {"epic"},
}


def wisp_read(issue_id: str, key: str, cwd: str) -> str:
    r = subprocess.run(
        ["grava", "wisp", "read", issue_id, key],
        capture_output=True, text=True, cwd=cwd,
    )
    return r.stdout.strip() if r.returncode == 0 else ""


def is_available(issue_id: str, cwd: str) -> bool:
    """True if issue is not already claimed by a pipeline."""
    phase = wisp_read(issue_id, "pipeline_phase", cwd)
    return phase in TERMINAL_PHASES


def _id(node: dict) -> str:
    return node.get("ID") or node.get("id", "")


def _type(node: dict) -> str:
    return (node.get("Type") or node.get("type", "")).lower()


def _title(node: dict) -> str:
    return node.get("Title") or node.get("title", "")


def _labels(node: dict) -> list[str]:
    raw = node.get("Labels") or node.get("labels") or []
    return [str(lb) for lb in raw]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--team", required=True,
        choices=["fix-bug", "epic-task", "qa", "task-generator"],
    )
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--target-repo", default=".")
    args = parser.parse_args(argv)

    cwd = args.target_repo
    results: list[dict] = []

    if args.team == "qa":
        # QA uses label filter (grava list -L), not grava ready
        r = subprocess.run(
            ["grava", "list", "-L", "qa-ready", "--json"],
            capture_output=True, text=True, cwd=cwd,
        )
        if r.returncode != 0:
            print(f"ERROR: {r.stderr.strip()}", file=sys.stderr)
            sys.exit(1)
        try:
            items = json.loads(r.stdout or "[]")
        except json.JSONDecodeError:
            items = []

        # grava list returns lowercase shape
        for item in items:
            iid = item.get("id", "")
            if iid and is_available(iid, cwd):
                results.append({"id": iid, "title": item.get("title", ""), "type": item.get("type", "")})
                if len(results) >= args.limit:
                    break

    else:
        # All other teams use grava ready.
        # `grava ready` caps at limit=20 by default, so push a high upstream
        # limit and then trim post-filter (some items will fail the team's
        # type filter or in-flight check and be skipped). 10x headroom is
        # sufficient for any plausible team backlog; if more is needed the
        # operator should call pick repeatedly.
        upstream_limit = max(args.limit * 10, 200)
        r = subprocess.run(
            ["grava", "ready", "--json", "--limit", str(upstream_limit)],
            capture_output=True, text=True, cwd=cwd,
        )
        if r.returncode != 0:
            print(f"ERROR: {r.stderr.strip()}", file=sys.stderr)
            sys.exit(1)
        try:
            items = json.loads(r.stdout or "[]")
        except json.JSONDecodeError:
            items = []

        allowed_types = TYPE_FILTER[args.team]

        for raw_item in items:
            # grava ready returns {Node: {ID, Type, ...}} — handle both shapes
            node = raw_item.get("Node") or raw_item

            iid = _id(node)
            itype = _type(node)
            ititle = _title(node)
            ilabels = _labels(node)

            if itype not in allowed_types:
                continue

            # task-generator team: must have tg:src:<page_id> label
            # grava ready --json does NOT include labels — need grava show
            if args.team == "task-generator":
                show_r = subprocess.run(
                    ["grava", "show", iid, "--json"],
                    capture_output=True, text=True, cwd=cwd,
                )
                full_labels: list[str] = []
                if show_r.returncode == 0:
                    try:
                        full_labels = [str(lb) for lb in json.loads(show_r.stdout).get("labels") or []]
                    except Exception:
                        pass
                if not any(lb.startswith("tg:src:") for lb in full_labels):
                    continue

            if iid and is_available(iid, cwd):
                results.append({"id": iid, "title": ititle, "type": itype})
                if len(results) >= args.limit:
                    break

    print(json.dumps(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
