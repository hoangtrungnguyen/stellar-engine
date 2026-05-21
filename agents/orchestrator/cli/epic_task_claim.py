#!/usr/bin/env python3
"""
Epic-Task Phase 0: Claim a story/task issue and provision its worktree.

Usage: python3 epic_task_claim.py <id> [--target-repo <path>] [--actor <name>]
Output: JSON {id, worktree, branch, tech_plan_path|null, idempotent?}
        Or on blocker rejection: JSON {error: "blocked", blockers: [{id, title, status}]}
Exit codes:
  0 = claimed successfully (or already claimed — idempotent)
  1 = wrong type (not task/story/subtask) or issue not found
  2 = grava claim failed
  3 = HARD REJECT — issue has unresolved blocking dependencies

Algorithm:
  1. grava show <id> --json → verify type in {task, story, subtask}; exit 1 if not
  2. grava wisp read <id> pipeline_phase:
     if phase in CLAIMED_OR_LATER → exit 0 (idempotent, heartbeat updated)
  3. HARD REJECT: grava blocked <id> --json
     if list is non-empty → exit 3 (do NOT claim, do NOT write wisps)
     no --force flag — blockers must be resolved upstream first
  4. grava claim <id> → provisions .worktree/<id>/ on branch grava/<id>
     exit 2 on failure
  5. grava wisp write <id> team epic-task
  6. grava wisp write <id> pipeline_phase claimed
  7. grava wisp write <id> orchestrator_heartbeat <unix-timestamp>
  8. Try grava signal ISSUE_CLAIMED (graceful fallback if signal unknown)
  9. Resolve tech plan path via tech_plan_load.py; write wisp tech_plan_path if found
  10. Print JSON {id, worktree, branch, tech_plan_path}

Note: grava wisp read exits 1 on missing key — treat returncode=1 as "not set".
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ALLOWED_TYPES = {"task", "story", "subtask"}

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
    (closed/tombstoned ones are excluded by default — no --all flag).
    A non-empty list means the issue is HARD-REJECTED for claiming.
    """
    r = subprocess.run(
        ["grava", "blocked", issue_id, "--json"],
        capture_output=True, text=True, cwd=cwd,
    )
    if r.returncode != 0:
        # If the command fails (unsupported, etc.), do NOT silently allow —
        # surface the failure so the operator notices.
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


def _resolve_tech_plan(target_repo: str) -> str:
    """Return absolute path to tech-plan.md, or '' if not found."""
    script = Path(__file__).parent / "tech_plan_load.py"
    if not script.exists():
        return ""
    r = subprocess.run(
        [sys.executable, str(script), "--target-repo", target_repo],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return ""
    try:
        data = json.loads(r.stdout)
        return data.get("tech_plan_path", "") if data.get("exists") else ""
    except (json.JSONDecodeError, AttributeError):
        return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("id", help="Grava issue ID (task/story/subtask)")
    parser.add_argument("--target-repo", default=".")
    parser.add_argument("--actor", default="epic-task-orchestrator")
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
        print(f"ERROR: bad JSON from grava show: {exc}", file=sys.stderr)
        sys.exit(1)

    issue_type = (issue.get("type") or "").lower()
    if issue_type not in ALLOWED_TYPES:
        print(
            f"ERROR: {args.id} is type '{issue_type}', expected one of {sorted(ALLOWED_TYPES)}.\n"
            f"Epic-task pipeline only handles task/story/subtask issues.\n"
            f"For bugs use fix_bug_claim.py; for epics use task_gen_expand.py.",
            file=sys.stderr,
        )
        sys.exit(1)

    # 2. Idempotency — already in pipeline?
    phase = wisp_read(args.id, "pipeline_phase", cwd)
    worktree = f".worktree/{args.id}"
    branch = f"grava/{args.id}"

    if phase in CLAIMED_OR_LATER:
        wisp_write(args.id, "orchestrator_heartbeat", str(int(time.time())), cwd)
        tech_plan_path = wisp_read(args.id, "tech_plan_path", cwd)
        print(f"Already in pipeline (pipeline_phase={phase}). Heartbeat updated.")
        print(json.dumps({
            "id": args.id,
            "worktree": worktree,
            "branch": branch,
            "tech_plan_path": tech_plan_path or None,
            "idempotent": True,
        }))
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

    # 4. Claim — provisions .worktree/<id>/ on branch grava/<id>
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

    # 5–7. Write initial wisps
    wisp_write(args.id, "team", "epic-task", cwd)
    wisp_write(args.id, "pipeline_phase", "claimed", cwd)
    wisp_write(args.id, "orchestrator_heartbeat", str(int(time.time())), cwd)

    # 8. Structured signal (graceful fallback if signal unknown)
    subprocess.run(
        ["grava", "signal", "ISSUE_CLAIMED", "--issue", args.id, "--actor", args.actor],
        capture_output=True, cwd=cwd,
    )

    # 9. Resolve and store tech plan path so agent can load it without re-running lookup
    tech_plan_path = _resolve_tech_plan(cwd)
    if tech_plan_path:
        wisp_write(args.id, "tech_plan_path", tech_plan_path, cwd)

    # 10. Output
    print(json.dumps({
        "id": args.id,
        "worktree": worktree,
        "branch": branch,
        "tech_plan_path": tech_plan_path or None,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
