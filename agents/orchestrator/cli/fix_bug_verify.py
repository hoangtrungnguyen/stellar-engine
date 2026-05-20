#!/usr/bin/env python3
"""
Fix-Bug Phase 2: Self-verify — run tests, linter, build in the worktree.

Usage: python3 fix_bug_verify.py <id> [--target-repo <path>]
                                  [--skip-verify] [--actor <name>]
                                  [--state-file <path>]
Output: JSON {id, verdict, attempt, details}
Exit codes:
  0 = pass
  2 = fail, max retries exceeded (labeled needs-human)
  5 = fail, retry available (fix code and re-run)

Algorithm:
  1. Load or init checkpoint from --state-file (default: .grava/fix-bug-<id>-verify.json)
     Checkpoint: {id, attempt, go_test, golangci_lint, go_build, verdict, started_at}
  2. If --skip-verify → verdict="pass", all checks="skipped"; go to step 5
  3. Run in .worktree/<id>/:
     a. go test ./...              → record exit code
     b. golangci-lint run ./...    → skip if not installed (shutil.which returns None)
     c. go build ./...             → record exit code
     verdict = "pass" if all non-skipped steps exit 0, else "fail"
  4. Save checkpoint (increments attempt counter for next run)
  5. grava wisp write <id> self_verify_result <verdict>
     grava wisp write <id> self_verify_retries <attempt-1>
  6. If verdict == "pass":
     grava label <id> --add self-verified
     grava signal CODER_DONE --issue <id> --actor <actor>  → pipeline_phase=coding_complete
     Print JSON; exit 0
  7. If verdict == "fail" and attempt <= MAX_RETRIES (2): exit 5 (fix and retry)
  8. If verdict == "fail" and attempt > MAX_RETRIES:
     grava label <id> --add needs-human
     Print JSON; exit 2
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

MAX_RETRIES = 2


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


def run_check(cmd: list[str], cwd: str) -> tuple[bool, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    output = (r.stdout + r.stderr)[:4096]
    return r.returncode == 0, output


def load_checkpoint(state_file: Path) -> dict:
    if state_file.exists():
        try:
            return json.loads(state_file.read_text())
        except Exception:
            pass
    return {}


def save_checkpoint(state_file: Path, data: dict) -> None:
    tmp = state_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(state_file)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("id", help="Grava bug issue ID")
    parser.add_argument("--target-repo", default=".")
    parser.add_argument("--skip-verify", action="store_true",
                        help="Skip all checks and force PASS verdict")
    parser.add_argument("--actor", default="fix-bug-verifier")
    parser.add_argument("--state-file", default=None)
    args = parser.parse_args(argv)

    cwd = args.target_repo
    worktree = os.path.join(cwd, ".worktree", args.id)

    state_path = args.state_file or os.path.join(cwd, ".grava", f"fix-bug-{args.id}-verify.json")
    state_file = Path(state_path)
    state_file.parent.mkdir(parents=True, exist_ok=True)

    checkpoint = load_checkpoint(state_file)
    attempt = checkpoint.get("attempt", 0) + 1
    started_at = checkpoint.get("started_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    details: dict[str, dict] = {}

    if args.skip_verify:
        for check in ("go_test", "golangci_lint", "go_build"):
            details[check] = {"pass": True, "output": "skipped (--skip-verify)"}
        verdict = "pass"
    else:
        if not os.path.isdir(worktree):
            print(
                f"ERROR: worktree not found: {worktree}\n"
                f"Run fix_bug_claim.py first to provision the worktree.",
                file=sys.stderr,
            )
            sys.exit(2)

        # go test
        ok, out = run_check(["go", "test", "./..."], worktree)
        details["go_test"] = {"pass": ok, "output": out}

        # golangci-lint (skip gracefully if not installed)
        if shutil.which("golangci-lint"):
            ok, out = run_check(["golangci-lint", "run", "./..."], worktree)
            details["golangci_lint"] = {"pass": ok, "output": out}
        else:
            details["golangci_lint"] = {"pass": True, "output": "skipped (golangci-lint not installed)"}

        # go build
        ok, out = run_check(["go", "build", "./..."], worktree)
        details["go_build"] = {"pass": ok, "output": out}

        verdict = "pass" if all(v["pass"] for v in details.values()) else "fail"

    # Save checkpoint
    save_checkpoint(state_file, {
        "id": args.id,
        "attempt": attempt,
        "verdict": verdict,
        "started_at": started_at,
        **{k: v["pass"] for k, v in details.items()},
    })

    # Write wisps
    wisp_write(args.id, "self_verify_result", verdict, cwd)
    wisp_write(args.id, "self_verify_retries", str(attempt - 1), cwd)
    wisp_write(args.id, "orchestrator_heartbeat", str(int(time.time())), cwd)

    result = {"id": args.id, "verdict": verdict, "attempt": attempt, "details": details}

    if verdict == "pass":
        subprocess.run(
            ["grava", "label", args.id, "--add", "self-verified"],
            capture_output=True, cwd=cwd,
        )
        # Signal coding_complete (compatible with /ship watcher)
        subprocess.run(
            ["grava", "signal", "CODER_DONE", "--issue", args.id, "--actor", args.actor],
            capture_output=True, cwd=cwd,
        )
        wisp_write(args.id, "pipeline_phase", "coding_complete", cwd)
        print(json.dumps(result))
        return 0

    # Fail path
    failing = [k for k, v in details.items() if not v["pass"]]
    print(
        f"Self-verify FAILED (attempt {attempt}/{MAX_RETRIES}). "
        f"Failing checks: {', '.join(failing)}",
        file=sys.stderr,
    )

    if attempt <= MAX_RETRIES:
        print("Fix the failing checks in the worktree and re-run fix_bug_verify.py.", file=sys.stderr)
        print(json.dumps(result))
        return 5

    # Max retries exceeded
    subprocess.run(
        ["grava", "label", args.id, "--add", "needs-human"],
        capture_output=True, cwd=cwd,
    )
    print(f"Max retries exceeded. Labeled 'needs-human'. Manual intervention required.", file=sys.stderr)
    print(json.dumps(result))
    return 2


if __name__ == "__main__":
    sys.exit(main())
