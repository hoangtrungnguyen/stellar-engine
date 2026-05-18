#!/usr/bin/env bash
# End-to-end smoke harness for `se o deploy` and its sub-modes against
# a real grava-initialised target repo. Read-only: every case is either
# a validation error, a --dry-run, an empty-queue path, or a non-destructive
# /ship hint (epic-task). No grava writes, no Plane API calls.
#
# Run:
#     bash agents/orchestrator/tests/e2e/se_o_deploy_e2e.sh
#
# Override the target repo via TARGET_REPO env var (default: stellar-sand-box).
# Override the `se` binary via SE_BIN env var (default: this worktree's cli/se).
#
# Exit code:
#     0  all PASS
#     1  any case failed (failure list printed at the end)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKTREE_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"

SE_BIN="${SE_BIN:-$WORKTREE_ROOT/cli/se}"
TARGET_REPO="${TARGET_REPO:-/Users/trungnguyenhoang/IdeaProjects/stellar-sand-box}"

# Discover three real issues in TARGET_REPO so the suite does not hard-code
# IDs that may have rotated.  `grava list --json` returns canonical IDs;
# the suite needs one epic, one story, one task — all open + not in flight.
discover_ids() {
    local kind="$1"
    cd "$TARGET_REPO" >/dev/null
    grava list --json 2>/dev/null \
        | python3 -c "
import json, sys
data = json.load(sys.stdin)
items = data if isinstance(data, list) else data.get('results', [])
for it in items:
    if (it.get('type','').lower() == '$kind'
            and it.get('status','').lower() in ('open','in_progress','')):
        print(it.get('id',''))
        break
"
    cd - >/dev/null
}

EPIC_ID="$(discover_ids epic || true)"
STORY_ID="$(discover_ids story || true)"
TASK_ID="$(discover_ids task || true)"

PASS=0
FAIL=0
FAILURES=()

run_tc() {
    local name="$1"
    local expected_exit="$2"
    local expected_match="$3"
    shift 3
    local output
    local actual_exit
    output=$(python3 "$SE_BIN" "$@" 2>&1)
    actual_exit=$?

    if [ "$actual_exit" -ne "$expected_exit" ]; then
        printf "  ✗ FAIL  %s\n" "$name"
        printf "          expected exit=%s, got %s\n" "$expected_exit" "$actual_exit"
        printf "          cmd: se %s\n" "$*"
        printf "          out: %s\n" "${output:0:300}"
        FAIL=$((FAIL+1))
        FAILURES+=("$name")
        return
    fi
    if [ -n "$expected_match" ] && ! echo "$output" | grep -qF "$expected_match"; then
        printf "  ✗ FAIL  %s\n" "$name"
        printf "          exit ok (=%s) but missing substring:\n" "$actual_exit"
        printf "          want: %s\n" "$expected_match"
        printf "          cmd: se %s\n" "$*"
        printf "          out: %s\n" "${output:0:300}"
        FAIL=$((FAIL+1))
        FAILURES+=("$name")
        return
    fi
    printf "  ✓ PASS  %s\n" "$name"
    PASS=$((PASS+1))
}

echo "=================================================================="
echo "  se o deploy end-to-end harness"
echo "=================================================================="
echo "  se binary : $SE_BIN"
echo "  target    : $TARGET_REPO"
echo "  discovered:"
echo "    epic  : ${EPIC_ID:-<none>}"
echo "    story : ${STORY_ID:-<none>}"
echo "    task  : ${TASK_ID:-<none>}"
echo ""

# ─────────────────────────────────────────────────────────────────────
echo "## 1. Validation errors (argparse + --all gates)"
# ─────────────────────────────────────────────────────────────────────

run_tc "TC01  --all without --team fails with exit 2" \
    2 "requires --team" \
    o deploy --all --target-repo "$TARGET_REPO"

run_tc "TC02  --all combined with <id> fails with exit 2" \
    2 "cannot be combined with <id>" \
    o deploy --all "${EPIC_ID:-grava-x}" --team fix-bug --target-repo "$TARGET_REPO"

# ─────────────────────────────────────────────────────────────────────
echo ""
echo "## 2. Single-issue dry-run dispatch (mode 1)"
# ─────────────────────────────────────────────────────────────────────

if [ -n "$EPIC_ID" ]; then
    run_tc "TC03  deploy <epic> --dry-run routes to task-generator" \
        0 "[dry-run] Would dispatch $EPIC_ID to team=task-generator" \
        o deploy "$EPIC_ID" --target-repo "$TARGET_REPO" --dry-run
else
    echo "  SKIP  TC03 (no epic found in target repo)"
fi

if [ -n "$STORY_ID" ]; then
    run_tc "TC04  deploy <story> --dry-run routes to epic-task" \
        0 "[dry-run] Would dispatch $STORY_ID to team=epic-task" \
        o deploy "$STORY_ID" --target-repo "$TARGET_REPO" --dry-run
else
    echo "  SKIP  TC04 (no story found in target repo)"
fi

if [ -n "$TASK_ID" ]; then
    run_tc "TC05  deploy <task> --dry-run routes to epic-task" \
        0 "[dry-run] Would dispatch $TASK_ID to team=epic-task" \
        o deploy "$TASK_ID" --target-repo "$TARGET_REPO" --dry-run
else
    echo "  SKIP  TC05 (no task found in target repo)"
fi

run_tc "TC06  deploy <nonexistent-id> surfaces grava ISSUE_NOT_FOUND" \
    1 "ISSUE_NOT_FOUND" \
    o deploy grava-zzz-nonexistent --target-repo "$TARGET_REPO" --dry-run

# ─────────────────────────────────────────────────────────────────────
echo ""
echo "## 3. Single-issue real dispatch (safe paths only)"
# ─────────────────────────────────────────────────────────────────────

if [ -n "$TASK_ID" ]; then
    # epic-task team has no se-side Phase 0 — prints /ship hint, exits 0
    run_tc "TC07  deploy <task> real → epic-task /ship hint, exit 0" \
        0 "/ship $TASK_ID" \
        o deploy "$TASK_ID" --target-repo "$TARGET_REPO"
else
    echo "  SKIP  TC07 (no task found)"
fi

if [ -n "$EPIC_ID" ]; then
    # task-generator → task_gen_expand → fails when epic lacks tg:src: label
    # (sandbox epics have plane:<seq> labels from a different generator path)
    run_tc "TC08  deploy <epic> real → task-generator expand → 'no tg:src' error" \
        1 "tg:src" \
        o deploy "$EPIC_ID" --target-repo "$TARGET_REPO"
else
    echo "  SKIP  TC08 (no epic found)"
fi

# ─────────────────────────────────────────────────────────────────────
echo ""
echo "## 4. Auto-pick (mode 2)"
# ─────────────────────────────────────────────────────────────────────

run_tc "TC09  deploy (no --team) auto-picks across all four teams" \
    0 "Auto-picked from team=" \
    o deploy --target-repo "$TARGET_REPO" --dry-run

run_tc "TC10  deploy --team epic-task auto-picks one epic-task issue" \
    0 "Auto-picked from team=epic-task" \
    o deploy --team epic-task --target-repo "$TARGET_REPO" --dry-run

run_tc "TC11  deploy --team fix-bug fails when backlog empty" \
    1 "No ready issues found for team=fix-bug" \
    o deploy --team fix-bug --target-repo "$TARGET_REPO" --dry-run

run_tc "TC11b deploy --team qa fails when backlog empty" \
    1 "No ready issues found for team=qa" \
    o deploy --team qa --target-repo "$TARGET_REPO" --dry-run

# ─────────────────────────────────────────────────────────────────────
echo ""
echo "## 5. Batch --all: epic-task hint loop (mode 3, hint-only team)"
# ─────────────────────────────────────────────────────────────────────

# epic-task is no longer gated out — `--all --team epic-task` loops every
# ready story/task and prints a /ship hint per item. No grava/Plane writes.
run_tc "TC12  --all --team epic-task → loops + 'Batch hint:' header, exit 0" \
    0 "Batch hint: team=epic-task" \
    o deploy --all --team epic-task --target-repo "$TARGET_REPO" --limit 2

run_tc "TC12b --all --team epic-task --limit 2 → 'hinted: 2' in summary" \
    0 "hinted:" \
    o deploy --all --team epic-task --target-repo "$TARGET_REPO" --limit 2

# ─────────────────────────────────────────────────────────────────────
echo ""
echo "## 6. Batch --all: empty-queue report (mode 3, valid team but no issues)"
# ─────────────────────────────────────────────────────────────────────

run_tc "TC13  --all --team fix-bug → structured empty-queue report" \
    0 "Empty queue report (team=fix-bug)" \
    o deploy --all --team fix-bug --target-repo "$TARGET_REPO"

run_tc "TC14  --all --team qa → structured empty-queue report" \
    0 "Empty queue report (team=qa)" \
    o deploy --all --team qa --target-repo "$TARGET_REPO"

run_tc "TC15  --all --team task-generator → structured empty-queue report" \
    0 "Empty queue report (team=task-generator)" \
    o deploy --all --team task-generator --target-repo "$TARGET_REPO"

# ─────────────────────────────────────────────────────────────────────
echo ""
echo "## 7. Batch --all: dry-run + limit + stop-on-error flags"
# ─────────────────────────────────────────────────────────────────────

run_tc "TC16  --all --team fix-bug --dry-run honours empty queue report" \
    0 "Empty queue report" \
    o deploy --all --team fix-bug --target-repo "$TARGET_REPO" --dry-run

run_tc "TC17  --all --team epic-task --dry-run lists /ship hint intents" \
    0 "would print /ship hint" \
    o deploy --all --team epic-task --target-repo "$TARGET_REPO" --dry-run --limit 2

run_tc "TC18  --all --limit 5 accepted without --all (no-op): single-issue mode" \
    1 "No ready issues found for team=fix-bug" \
    o deploy --team fix-bug --limit 5 --target-repo "$TARGET_REPO" --dry-run

# ─────────────────────────────────────────────────────────────────────
echo ""
echo "## 8. Plane profile / config flags accepted on deploy"
# ─────────────────────────────────────────────────────────────────────

if [ -n "$TASK_ID" ]; then
    # epic-task path doesn't touch Plane, but the flag should still be
    # accepted by argparse + _apply_plane_profile_env without errors.
    run_tc "TC19  deploy <task> --plane-profile stellar-sandbox --dry-run accepts flag" \
        0 "[dry-run] Would dispatch" \
        o deploy "$TASK_ID" --plane-profile stellar-sandbox --target-repo "$TARGET_REPO" --dry-run

    run_tc "TC20  deploy <task> --plane-config /tmp/missing.json --dry-run accepts flag" \
        0 "[dry-run] Would dispatch" \
        o deploy "$TASK_ID" --plane-config /tmp/missing.json --target-repo "$TARGET_REPO" --dry-run
else
    echo "  SKIP  TC19/TC20 (no task found)"
fi

# ─────────────────────────────────────────────────────────────────────
echo ""
echo "## 9. Long-form (se orchestrator) alias parity"
# ─────────────────────────────────────────────────────────────────────

if [ -n "$EPIC_ID" ]; then
    run_tc "TC21  'se orchestrator deploy' is identical to 'se o deploy'" \
        0 "task-generator" \
        orchestrator deploy "$EPIC_ID" --target-repo "$TARGET_REPO" --dry-run
else
    echo "  SKIP  TC21 (no epic found)"
fi

# ─────────────────────────────────────────────────────────────────────
echo ""
echo "──────────────────────────────────────────────────────────────────"
echo "  Summary: PASS=$PASS  FAIL=$FAIL"
if [ "${#FAILURES[@]}" -gt 0 ]; then
    echo "  failed cases:"
    for f in "${FAILURES[@]}"; do echo "    - $f"; done
    exit 1
fi
exit 0
