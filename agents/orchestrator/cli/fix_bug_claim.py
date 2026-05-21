#!/usr/bin/env python3
"""
Fix-Bug Phase 0: Claim a bug issue and provision its worktree.

Usage: python3 fix_bug_claim.py <id> [--target-repo <path>] [--actor <name>]
Output: JSON {id, worktree, branch, idempotent?}
        Or on blocker rejection: JSON {error: "blocked", blockers: [{id, title, status}]}
Exit codes:
  0 = claimed successfully (or already claimed — idempotent)
  1 = not a bug type or issue not found
  2 = grava claim failed
  3 = HARD REJECT — issue has unresolved blocking dependencies

Algorithm:
  1. grava show <id> --json → verify type == "bug"; exit 1 if not
  2. grava wisp read <id> pipeline_phase:
     if phase in CLAIMED_OR_LATER → exit 0 (idempotent, print current state)
  3. HARD REJECT: grava blocked <id> --json
     if list is non-empty → exit 3 (do NOT claim, do NOT write wisps)
     no --force flag — blockers must be resolved upstream first
  4. grava claim <id> → provisions .worktree/<id>/ on branch grava/<id>
     exit 2 on failure
  5. grava wisp write <id> team fix-bug
  6. grava signal ISSUE_CLAIMED --issue <id> --actor <actor>
     (sets pipeline_phase=claimed; falls back to direct wisp write if signal fails)
  7. grava wisp write <id> orchestrator_heartbeat <unix-timestamp>
  8. Print JSON {id, worktree: ".worktree/<id>", branch: "grava/<id>"}

Note: grava wisp read exits 1 on missing key (not 0) — treat returncode=1 as "not set".
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


def _check_blockers(issue_id: str, cwd: str) -> list[dict]:
    """Return list of active blockers for issue_id (empty list = unblocked).

    Calls `grava blocked <id> --json` which returns only OPEN blockers
    (closed/tombstoned ones are excluded by default). A non-empty list
    means the issue is HARD-REJECTED for claiming.
    """
    r = subprocess.run(
        ["grava", "blocked", issue_id, "--json"],
        capture_output=True, text=True, cwd=cwd,
    )
    if r.returncode != 0:
        # Surface the failure rather than silently allowing the claim.
        print(
            f"WARNING: `grava blocked` failed (exit {r.returncode}): "
            f"{r.stderr.strip()}\nProceeding without blocker check.",
            file=sys.stderr,
        )
        return []
    try:
        data = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("id", help="Grava bug issue ID")
    parser.add_argument("--target-repo", default=".")
    parser.add_argument("--actor", default="fix-bug-orchestrator")
    args = parser.parse_args(argv)

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
        return 0

    # 3. HARD REJECT — if any unresolved blocker exists, refuse to claim.
    #    grava claim itself does NOT validate this, so we gate it here.
    #    No --force flag: blockers must be resolved upstream first.
    blockers = _check_blockers(args.id, cwd)
    if blockers:
        blocker_summary = ", ".join(
            f"{b.get('id', '?')} ({b.get('status', '?')})" for b in blockers[:5]
        )
        print(
            f"REJECTED: {args.id} is blocked by {len(blockers)} unresolved "
            f"dependency/dependencies: {blocker_summary}\n"
            f"Resolve blockers first, then re-run.",
            file=sys.stderr,
        )
        print(json.dumps({
            "id": args.id,
            "error": "blocked",
            "blockers": [
                {
                    "id": b.get("id", ""),
                    "title": b.get("title", ""),
                    "status": b.get("status", ""),
                }
                for b in blockers
            ],
        }))
        sys.exit(3)

    # 4. Claim (provisions .worktree/<id>/ on branch grava/<id>)
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

    # 5. Write initial wisps
    wisp_write(args.id, "team", "fix-bug", cwd)
    wisp_write(args.id, "pipeline_phase", "claimed", cwd)
    wisp_write(args.id, "orchestrator_heartbeat", str(int(time.time())), cwd)

    # 6. Try structured signal (may not exist; fall back gracefully)
    subprocess.run(
        ["grava", "signal", "ISSUE_CLAIMED", "--issue", args.id, "--actor", args.actor],
        capture_output=True, cwd=cwd,
    )

    print(json.dumps({"id": args.id, "worktree": worktree, "branch": branch}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
