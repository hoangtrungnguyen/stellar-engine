#!/usr/bin/env python3
"""
Fix-Bug Phase 0: Claim a bug issue and provision its worktree.

Usage: python3 fix_bug_claim.py <id> [--target-repo <path>] [--actor <name>]
Output: JSON {id, worktree, branch, idempotent?}
Exit codes:
  0 = claimed successfully (or already claimed — idempotent)
  1 = not a bug type or issue not found
  2 = grava claim failed
"""
import argparse
import json
import subprocess
import sys
import time

# Phases at or past "claimed" — re-running is idempotent
CLAIMED_OR_LATER = {
    "claimed", "coding_complete", "pr_created", "pr_awaiting_merge",
    "review_approved", "complete", "failed",
}


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("id", help="Grava bug issue ID")
    parser.add_argument("--target-repo", default=".")
    parser.add_argument("--actor", default="fix-bug-orchestrator")
    args = parser.parse_args()

    cwd = args.target_repo

    # 1. Fetch and validate type
    r = subprocess.run(
        ["grava", "show", args.id, "--json"],
        capture_output=True, text=True, cwd=cwd,
    )
    if r.returncode != 0:
        print(f"ERROR: issue not found: {args.id}", file=sys.stderr)
        sys.exit(1)

    try:
        issue = json.loads(r.stdout)
    except json.JSONDecodeError as exc:
        print(f"ERROR: bad JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    issue_type = (issue.get("type") or "").lower()
    if issue_type != "bug":
        print(
            f"ERROR: {args.id} is type '{issue_type}', not 'bug'.\n"
            f"Fix-bug pipeline only handles bug-type issues.\n"
            f"Use /ship for tasks/stories, or check routing.",
            file=sys.stderr,
        )
        sys.exit(1)

    # 2. Idempotency — already in pipeline?
    phase = wisp_read(args.id, "pipeline_phase", cwd)
    worktree = f".worktree/{args.id}"
    branch = f"grava/{args.id}"

    if phase in CLAIMED_OR_LATER:
        wisp_write(args.id, "orchestrator_heartbeat", str(int(time.time())), cwd)
        print(f"Already in pipeline (pipeline_phase={phase}). Heartbeat updated.")
        print(json.dumps({"id": args.id, "worktree": worktree, "branch": branch, "idempotent": True}))
        sys.exit(0)

    # 3. Claim (provisions .worktree/<id>/ on branch grava/<id>)
    claim_r = subprocess.run(
        ["grava", "claim", args.id],
        capture_output=True, text=True, cwd=cwd,
    )
    if claim_r.returncode != 0:
        print(
            f"ERROR: grava claim failed:\n{claim_r.stderr.strip()}\n"
            f"Possible causes: already claimed by another session, or grava not initialised.",
            file=sys.stderr,
        )
        sys.exit(2)

    # 4. Write initial wisps
    wisp_write(args.id, "team", "fix-bug", cwd)
    wisp_write(args.id, "pipeline_phase", "claimed", cwd)
    wisp_write(args.id, "orchestrator_heartbeat", str(int(time.time())), cwd)

    # 5. Try structured signal (may not exist; fall back gracefully)
    subprocess.run(
        ["grava", "signal", "ISSUE_CLAIMED", "--issue", args.id, "--actor", args.actor],
        capture_output=True, cwd=cwd,
    )

    print(json.dumps({"id": args.id, "worktree": worktree, "branch": branch}))


if __name__ == "__main__":
    main()
