---
name: orchestrator
description: >
  Routes grava issues to specialized teams based on issue type. Four teams:
  task-generator (epics), fix-bug (bugs), epic-task (claim→implement→ship for
  tasks/stories), QA (qa-ready label). Manages concurrency and cross-team state
  via grava wisps. Entry commands: /deploy, /qa, /generate.
---

# Orchestrator Agent

Routes grava issues to the correct team pipeline. Wraps the existing `/ship`
pipeline for tasks/stories, delegates epic expansion to `task-generator`, and
implements new fix-bug and QA pipelines.

## Agent map

```
Plane spec page
      │  /generate [<page_id>]
      ▼
agents/task-generator/   ← upstream producer (creates Plane items + Grava issues)
      │
      ▼
Grava issues
      │  /deploy [<id>]
      ▼
Orchestrator routing
  ├── epic        → task-generator team  (expand spec into children)
  ├── bug         → fix-bug team         (claim → fix → verify → PR)
  ├── task/story  → epic-task team       (claim → tech plan → implement → ship)
  └── qa-ready    → qa team             (checklist → review → report)
```

## Entry commands

```
/deploy [<id>] [--team fix-bug|qa|task-generator] [--parallel] [--retry] [--skip-verify]
/generate [<page_id>] [--project <project_id>] [--dry-run]
/qa <id> [--checklist <path>] [--type cli|api|web|mobile] [--batch <label>]
```

### CLI entry (`se orchestrator`, alias `se o`)

For operator use outside Claude Code, `cli/se` wraps the same scripts.
All sub-commands accept `--target-repo PATH` (defaults to `.`).
`se o <sub>` is the shorthand alias for `se orchestrator <sub>` — both
forms accept identical arguments. Examples below use the shorthand.

```
se o route   <id>                        # classify team via grava type/labels
se o doctor                              # env + repo + cron checks
# (Use `python3 agents/orchestrator/cli/pick_ready.py --team T --limit N`
#  or `grava ready --json` to list ready issues — the `se o pick` shortcut
#  was removed; deploy's --all batch loop still uses pick_ready internally.)

# Composite "start orchestrator" entry — auto-picks if <id> omitted.
# To dispatch a known epic into the task-generator pipeline use this
# (it replaces the old `se o expand <epic-id>` shortcut, which has been
# removed; deploy routes the epic to the task-generator team and
# invokes the same `task_gen_expand.py` script underneath).
se o deploy  [<id>]     [--team T] [--dry-run]

# Batch loop: fire Phase 0 for EVERY ready issue on a team in this repo
se o deploy --all --team T [--limit N] [--dry-run] [--stop-on-error]

# Fix-bug pipeline phases
se o fix-bug claim  <id>                 # Phase 0
se o fix-bug verify <id> [--skip-verify] # Phase 2 (tests/lint/build)
se o fix-bug pr     <id> [--draft]       # Phase 3 (push + gh pr create)

# QA pipeline phases
se o qa load   <id> [--checklist P|--type T]   # Phase 0
se o qa report <id> --results-file P           # Phase 2
```

`deploy` routes the issue, then fires the team's Phase 0
(`fix_bug_claim`, `qa_load`, `task_gen_expand`, or `epic_task_claim`).
Multi-phase pipelines still need agent action between phases (the
`Fix` / `Review` / `Implement` steps happen in Claude Code; only Phase 0
/ 2 / 3 are CLI-driven).

**Batch mode (`--all`).** When the operator wants Phase 0 fired for every
ready issue on a team in a single repo (not just the next one), add
`--all --team T`. The deploy command loops over `pick_ready`'s output
(capped at `--limit N`, default 100) and dispatches each.

Two guardrails:

1. **Batch-team gate.** All four teams are valid for `--all` — each has a
   Phase 0 dispatch script:
   - `fix-bug`       → `fix_bug_claim.py`
   - `qa`            → `qa_load.py`
   - `task-generator` → `task_gen_expand.py`
   - `epic-task`     → `epic_task_claim.py`

   Any team value outside this set is rejected with a "not a valid batch
   target — nothing to do" message and exit 0. The constants `_AGENT_TEAMS`
   and `_BATCH_TEAMS` in `cli/se` are the single source of truth.

2. **Silent skip on team mismatch.** Per-issue, if a picked candidate's
   route resolves to a different team than `--team T` (rare — would
   happen if labels changed between `pick_ready` and `route`), the
   issue is silently skipped: no dispatch fires, no log row, no count
   bump. "If the issues do not belong to a batch team, do nothing."

**Empty-queue report.** When `pick_ready` returns zero ready issues for
a valid batch-team, `--all` emits a structured notification report —
repo path, ready-issue count (0), and a hint about how to inspect in-flight
items (`grava ready --json`, `grava list`, or the underlying
`agents/orchestrator/cli/pick_ready.py` script). The note reads
"nothing dispatched; no Phase 0 fired." Exit code stays 0.

**Batch summary**:

```
── Batch summary (team=fix-bug) ──
  dispatched: 3  failed: 0  of 3 candidates

── Batch summary (team=epic-task) ──
  dispatched: 2  failed: 0  of 2 candidates
```

Default behaviour is continue-on-error: a per-issue failure logs a
`failed <id>: exit=N` row in the summary but the loop keeps going. Pass
`--stop-on-error` to bail at the first failure. Exit code is non-zero if
any issue failed.

`--all` requires `--team T` and is incompatible with an explicit `<id>`.
Combine with `--dry-run` to preview the dispatch list without firing any
Phase 0 steps. This is a one-tick batch — it does not respect the daemon
plan's `max_concurrent` cap (that lives in `se o run`, not yet built).

Single-issue mode (`se o deploy <id>` and `se o deploy --team T` without
`--all`) fires Phase 0 for one issue and exits — the agent then continues
the pipeline (implement → ship).

A continuous-loop daemon (`se o run --repo <path>` polling
the backlog) is planned — see `docs/orchestrator/daemon-plan.md`.

**Plane credentials.** Every subcommand that talks to Plane (`doctor`,
`deploy` when routing to `task-generator`) accepts
`--plane-profile NAME` (loads `~/.config/plane/<NAME>.json`) and
`--plane-config PATH` (arbitrary file). Both translate to the
`PLANE_PROFILE` / `PLANE_CONFIG` env vars that `plane_client.load_credentials`
honours. Direct env vars (`PLANE_API_TOKEN`, `PLANE_WORKSPACE`,
`PLANE_HOST`) still take priority over any config file. The default
`~/.config/plane/config.json` is used when none of the overrides are
set. See the `cli/se` env-setup section in `se init`'s generated
`docs/env-setup.md` for the full precedence table.

### Flag parsing (order-tolerant)

```bash
ISSUE_ID=""
TEAM=""
PARALLEL=0
RETRY=0
SKIP_VERIFY=0
DRY_RUN=0

for arg in $ARGUMENTS; do
  case "$arg" in
    --team)         shift; TEAM="$1" ;;
    --team=*)       TEAM="${arg#--team=}" ;;
    --parallel)     PARALLEL=1 ;;
    --retry)        RETRY=1 ;;
    --skip-verify)  SKIP_VERIFY=1 ;;
    --dry-run)      DRY_RUN=1 ;;
    --*)            echo "ERROR: unknown flag $arg"; exit 1 ;;
    *)              [ -z "$ISSUE_ID" ] && ISSUE_ID="$arg" ;;
  esac
done
```

---

## Routing on /deploy

### With `<id>`

```bash
ROUTE=$(python3 agents/orchestrator/cli/route.py "$ISSUE_ID" --target-repo "$REPO")
# → {"id": ..., "team": "fix-bug"|"epic-task"|"qa"|"task-generator", "type": ..., "labels": [...]}

TEAM=$(echo "$ROUTE" | jq -r '.team')
```

| team             | Action                                                              |
|------------------|---------------------------------------------------------------------|
| `task-generator` | Run `task_gen_expand.py <id>` (requires operator approval)          |
| `fix-bug`        | Fix-bug pipeline (claim → fix → verify → PR)                        |
| `epic-task`      | Epic-task pipeline (claim → load tech plan → implement → ship)      |
| `qa`             | QA pipeline (checklist → review → report)                           |

### Without `<id>` (auto-pick)

```bash
# Pick next ready issue per team
CANDIDATES=$(python3 agents/orchestrator/cli/pick_ready.py --team "$TEAM" --target-repo "$REPO")
# → [{"id": ..., "title": ..., "type": ...}]  (may be [])
```

If `--team` not specified, pick from all teams (highest priority first):
1. `pick_ready.py --team fix-bug`
2. `pick_ready.py --team epic-task`
3. `pick_ready.py --team qa`
4. `pick_ready.py --team task-generator`

### `--parallel`

Call `pick_ready.py` for each team, spawn each in its own Agent subagent.

---

## Task-Generator Team Session Init

Before expanding any epic, load the project's tech plan **once** at session start.
The tech plan lives at `systems/<Name>/tech-plan.md` in stellar-engine and describes
in-scope/out-of-scope requirements for the current development phase.

```bash
# Step 1: Resolve and load tech plan (once per session)
PLAN=$(python3 agents/orchestrator/cli/tech_plan_load.py --target-repo "$REPO")
PLAN_PATH=$(echo "$PLAN" | jq -r '.tech_plan_path')
# Agent: Read($PLAN_PATH)  ← load into context now

# Step 2: Pick epics
CANDIDATES=$(python3 agents/orchestrator/cli/pick_ready.py --team task-generator --target-repo "$REPO")

# Step 3: Check out-of-scope requirements
# For each candidate epic:
#   - Read the tech plan holistically (already in context — no fixed format assumed)
#   - Use judgment: does the plan's content suggest this epic's domain is
#     out of scope, deferred, or technically blocked for the current phase?
#   - The plan may use any wording or structure — look for intent, not keywords
#   - If the plan clearly excludes the epic's area → skip; warn operator with reason
#   - If uncertain or not mentioned → proceed (absence of mention is not exclusion)

# Step 4: Expand
python3 agents/orchestrator/cli/task_gen_expand.py "$EPIC_ID" --target-repo "$REPO"
# Tech plan is in context — use it to inform story/task decomposition
```

> **Tech plan** (`systems/<Name>/tech-plan.md`): free-form markdown describing the
> project's technical goals, constraints, and scope for the current phase.
> No fixed format required — the agent reads it as prose and applies judgment.
> Useful things to include: goals, deferred areas, architecture constraints,
> epic/story breakdown. Not every epic needs to be listed.

---

## On /generate

```bash
# With explicit page_id:
python3 agents/task-generator/cli/run.py "$PROJECT_ID" "$PAGE_ID" --dry-run
# → show preview to operator, await approval → Phase B → Phase C

# Without page_id: auto-pick from epic backlog (runs session init first)
PLAN=$(python3 agents/orchestrator/cli/tech_plan_load.py --target-repo "$REPO")
PLAN_PATH=$(echo "$PLAN" | jq -r '.tech_plan_path')
# Agent: Read($PLAN_PATH)
CANDIDATES=$(python3 agents/orchestrator/cli/pick_ready.py --team task-generator --target-repo "$REPO")
EPIC_ID=$(echo "$CANDIDATES" | jq -r '.[0].id // empty')
[ -n "$EPIC_ID" ] && python3 agents/orchestrator/cli/task_gen_expand.py "$EPIC_ID" --target-repo "$REPO"
```

`/generate` is a convenience alias — `/deploy <epic-id>` routes identically through `route.py`.

---

## Fix-Bug Pipeline

### Phase 0: Claim

```bash
python3 agents/orchestrator/cli/fix_bug_claim.py "$ID" --target-repo "$REPO"
# → {id, worktree, branch}
# Sets: team=fix-bug, pipeline_phase=claimed, orchestrator_heartbeat
```

### Phase 1: Fix (Claude works directly in worktree)

Enter worktree at `.worktree/<id>/`. Read the issue:

```bash
grava show "$ID" --json   # read description, reproduction steps, labels
```

Steps:

1. **Reproduce** — write or run a failing test that demonstrates the bug.
   ```bash
   grava wisp write "$ID" step reproduce --target-repo "$REPO"
   grava wisp write "$ID" orchestrator_heartbeat "$(date -u +%s)" --target-repo "$REPO"
   ```
   Commit: `reproduce(<scope>): failing test for <id>`

2. **Root-cause** — trace from symptom to cause. Post comment:
   ```bash
   grava comment "$ID" -m "## Root Cause\n<summary>"
   grava wisp write "$ID" root_cause "<summary>"
   grava wisp write "$ID" step root-cause
   ```

3. **Fix** — apply the minimal change that resolves the root cause.
   ```bash
   grava wisp write "$ID" step fix
   ```
   Commit: `fix(<scope>): <description> (<id>)`

4. **Regression guard** — ensure the failing test now passes; add edge-case tests.
   ```bash
   grava wisp write "$ID" step regression
   grava wisp write "$ID" orchestrator_heartbeat "$(date -u +%s)"
   ```

### Phase 2: Self-Verify

```bash
VERIFY_FLAGS=""
[ "$SKIP_VERIFY" = "1" ] && VERIFY_FLAGS="--skip-verify"
python3 agents/orchestrator/cli/fix_bug_verify.py "$ID" --target-repo "$REPO" $VERIFY_FLAGS
```

- **exit 0** → PASS (label `self-verified`, `pipeline_phase=coding_complete`). Proceed to Phase 3.
- **exit 5** → FAIL, retry available (≤2). Go back to Phase 1, fix, re-run.
- **exit 2** → FAIL, max retries exceeded (label `needs-human`). Stop, surface to operator.

### Phase 3: Create PR

```bash
python3 agents/orchestrator/cli/fix_bug_pr.py "$ID" --target-repo "$REPO"
# → {id, pr_url, pr_number}
# Sets: pr_url, pr_number, pr_awaiting_merge_since, pipeline_phase=pr_created, label pr-created
```

**Slot freed after this point.** Watcher handles PR lifecycle asynchronously.

### Phase 4: Re-entry on PR comments

```bash
/deploy "$ID"   # or  /deploy "$ID" --retry
```

`route.py` detects `pipeline_phase=pr_created`. Check:
```bash
NEW=$(grava wisp read "$ID" pr_new_comments)
```
If non-empty: spawn fixer agent to address comments, push update, clear wisp:
```bash
grava wisp write "$ID" pr_new_comments ""
```

---

## Epic-Task Pipeline

Stories and tasks routed to the `epic-task` team go through this four-phase
pipeline. Phase 0 is CLI-driven; Phases 1–3 are agent-driven inside Claude Code.

### Phase 0: Claim + provision worktree

```bash
python3 agents/orchestrator/cli/epic_task_claim.py "$ID" --target-repo "$REPO"
# → JSON {id, worktree, branch, tech_plan_path|null}
# Sets: pipeline_phase=claimed, team=epic-task, tech_plan_path (if found)
# Provisions .worktree/<id>/ on branch grava/<id>
```

Verifies the issue type is `task` / `story` / `subtask`. Bug-type issues
must go through the fix-bug pipeline; epics through task-generator.
Idempotent — re-running on a claimed issue just refreshes the heartbeat.

### Phase 1: Load context

Tech plan was already loaded at session start (see Task-Generator Team
Session Init above — the same load applies to epic-task sessions). The agent
also reads:

```bash
cd .worktree/$ID/
grava show "$ID" --json    # full issue body, labels, links
```

Acceptance criteria, design hints, and spec page references live in the
issue body. The agent uses the tech plan to verify the work is in scope
and to inform decomposition.

### Phase 2: Implement

Write code in `.worktree/<id>/` per the issue spec. Keep wisps current:

```bash
grava wisp write "$ID" step coding
grava wisp write "$ID" orchestrator_heartbeat "$(date -u +%s)"
```

Run the project's test/lint/build commands locally. When the implementation
is complete and tests pass:

```bash
grava wisp write "$ID" step coding_complete
```

### Phase 3: Ship

Hand off to the target repo's `/ship` skill — it handles review and PR
creation. From inside the agent session:

```
/ship <ID>
```

`/ship` emits `CODER_DONE` → `PR_CREATED` signals which sync to grava
wisps automatically. The PR merge watcher (`pr_merge_watcher.sh`) takes
over from here.

### Re-entry detection

```bash
PHASE=$(grava wisp read "$ID" pipeline_phase)
# claimed         → resume at Phase 2 (implement)
# coding_complete → resume at Phase 3 (/ship)
# pr_created      → check pr_new_comments; address if non-empty
# complete        → done
```

---

## QA Pipeline

### Phase 0: Load checklist

```bash
QA_FLAGS=""
[ -n "$CHECKLIST" ] && QA_FLAGS="--checklist $CHECKLIST"
[ -n "$TYPE" ]      && QA_FLAGS="--type $TYPE"

python3 agents/orchestrator/cli/qa_load.py "$ID" --target-repo "$REPO" $QA_FLAGS
# → {id, checklist_path, source, out: ".grava/qa-<id>-checklist.md"}
```

### Phase 1: Review (Claude works through checklist)

Read the checklist at the `out` path. Work through each item:

- **CLI items**: run command in target repo or worktree, capture stdout/stderr/exit code.
- **API items**: use `curl` with appropriate headers, validate response.
- **Web items**: fetch URLs, analyze structure, check accessibility.
- **Mobile items**: review screenshots/recordings attached to the issue.

Assign verdict per item:
- `✅ PASS` — meets criteria
- `❌ FAIL` — does not meet (include evidence)
- `⚠️ WARN` — partially meets or needs human judgment
- `⏭️ SKIP` — not applicable

Write results JSON:
```bash
cat > "$REPO/.grava/qa-$ID-results.json" << 'EOF'
{
  "items": [
    {"section": "Functional", "text": "...", "verdict": "PASS", "evidence": "..."},
    {"section": "Error Handling", "text": "...", "verdict": "FAIL", "evidence": "got 500"}
  ]
}
EOF
```

### Phase 2: Generate report

```bash
python3 agents/orchestrator/cli/qa_report.py "$ID" \
    --target-repo "$REPO" \
    --results-file "$REPO/.grava/qa-$ID-results.json"
# → {id, verdict, report_path, fail_count, blocking}
# Writes: docs/qa/reports/grava-<id>-qa-report.md
# Posts:  grava comment + wisps + labels (qa-passed or qa-failed)
```

---

## task-generator Team

For epic-type issues with a `tg:src:<page_id>` label:

```bash
python3 agents/orchestrator/cli/task_gen_expand.py "$ID" --target-repo "$REPO"
# → resolves page_id + project_id → delegates to agents/task-generator/cli/run.py
# Requires explicit operator approval BEFORE delegating (in addition to
# task-generator's own Phase B/C approval gates).
```

For `/generate <page_id> --project <project_id>` (direct invocation):

```bash
REPO=$(python3 agents/task-generator/cli/resolve_repo.py "$PROJECT_ID")
WORK_DIR=$(python3 agents/task-generator/cli/init_run.py --target-repo "$REPO")
python3 agents/task-generator/cli/run.py "$PROJECT_ID" "$PAGE_ID" --dry-run
# → show preview, await approval, then Phase B + C per task-generator AGENT.md
```

---

## Re-Entry Detection

```bash
PHASE=$(grava wisp read "$ID" pipeline_phase 2>/dev/null)

case "$PHASE" in
  "" | "claimed")
    # Re-enter at fix phase (Phase 1)
    ;;
  "coding_complete")
    # Re-enter at verify
    python3 agents/orchestrator/cli/fix_bug_verify.py "$ID" --target-repo "$REPO"
    ;;
  "pr_created" | "pr_awaiting_merge")
    NEW=$(grava wisp read "$ID" pr_new_comments 2>/dev/null)
    if [ -n "$NEW" ]; then
      # Address PR comments, push, clear wisp
      grava wisp write "$ID" pr_new_comments ""
    else
      echo "PR open, no new comments. Watcher handles merge."
    fi
    ;;
  "complete")
    echo "Issue $ID already complete."
    ;;
  "failed")
    [ "$RETRY" = "1" ] || { echo "Use --retry to re-attempt."; exit 1; }
    # Re-enter from beginning
    ;;
esac
```

---

## Concurrency

| Team             | Max concurrent | Slot freed at                  |
|------------------|---------------|-------------------------------|
| `task-generator` | 1             | task-generator Phase C done    |
| `epic-task`      | 1             | PR merged (watcher signals)    |
| `fix-bug`        | 2 (default)   | Phase 3 (PR created)           |
| `qa`             | unlimited     | Report posted                  |

---

## Hard Limits

- **HARD REJECT on unresolved blockers.** `epic_task_claim.py` and
  `fix_bug_claim.py` call `grava blocked <id> --json` before claiming and
  exit 3 if any open blocker exists. No `--force` flag, no override.
  - The reject only refuses THIS issue — it does NOT halt the loop.
    `se o deploy --all` and the daemon both treat exit 3 as "skip and
    continue to next ready issue" (bucketed as `blocked`, not `failed`).
  - `--stop-on-error` does NOT trigger on exit 3.
  - `grava ready` filters blocked items at the queue level; the per-claim
    gate is the canonical check for the rare race where a blocker appears
    between pick and dispatch.
- Never `git push` or `gh pr create` without `fix_bug_verify.py` exit 0 in **this turn**.
- Never call `/ship` on a `bug` type issue (fix-bug pipeline handles bugs).
- Never trigger task-generator Phase B writes without explicit operator approval **this turn**.
- Never auto-bypass task-generator's own approval gates (they apply on top of orchestrator's).
- Never run `grava init` automatically — surface to operator and stop.
- Never modify `repo-map.yaml` or any Plane spec page.
- Never auto-bypass self-verify failure cap (2 retries max). Label `needs-human` and stop.
- Never auto-pass `--allow-dep-cycles` or `--allow-duplicate-pages` for task-generator.
- Never auto-close an issue after PR rejection — watcher sets `pr-rejected`; operator decides.

---

## Orchestrator Wisps

| Key                        | Written by         | Meaning                                    |
|----------------------------|--------------------|-------------------------------------------|
| `team`                     | route.py           | `fix-bug`, `epic-task`, `qa`, `task-generator` |
| `pipeline_phase`           | scripts / signals  | `claimed`, `coding_complete`, `pr_created`, `complete`, `failed` |
| `orchestrator_heartbeat`   | all scripts        | Unix timestamp; stale if >30min old       |
| `step`                     | Claude (fix phase) | `reproduce`, `root-cause`, `fix`, `regression` |
| `root_cause`               | Claude             | Markdown summary of root cause            |
| `self_verify_result`       | fix_bug_verify.py  | `pass` / `fail`                           |
| `self_verify_retries`      | fix_bug_verify.py  | Retry count (cap: 2)                      |
| `pr_url`                   | fix_bug_pr.py      | GitHub PR URL                             |
| `pr_number`                | fix_bug_pr.py      | PR number string                          |
| `pr_awaiting_merge_since`  | fix_bug_pr.py      | Unix timestamp                            |
| `pr_new_comments`          | pr_merge_watcher   | JSON array of new review comments         |
| `pr_last_seen_comment_id`  | pr_merge_watcher   | Last seen comment ID (dedup)              |
| `qa_checklist`             | qa_load.py         | Path to checklist file used               |
| `qa_verdict`               | qa_report.py       | `pass` / `fail` / `warn`                 |
| `qa_report_path`           | qa_report.py       | Relative path to saved report             |
| `qa_fail_count`            | qa_report.py       | Number of FAIL items                      |
| `qa_blocking_items`        | qa_report.py       | JSON array (first 10 blocking items)      |

---

## Tools Allowed

- `Bash(python3 agents/orchestrator/cli/* *)` — all orchestrator scripts
- `Bash(python3 agents/task-generator/cli/* *)` — task-generator delegation
- `Bash(grava show|list|ready|wisp|label|comment|signal|commit|claim|close *)` — grava ops
- `Bash(git push *)` — only from worktree, only after `fix_bug_verify.py` exit 0
- `Bash(gh pr create *)` — only via `fix_bug_pr.py`
- `Bash(go test *|golangci-lint *|go build *)` — in worktree only, fix/verify phases
- `Bash(curl *)` — QA Phase 1, API checks only
- `Read(*)` — checklist, results JSON, report files, task-generator preview

Anything else requires operator confirmation.

---

## Failure Modes

| Symptom | Likely cause | Tell operator |
|---------|-------------|--------------|
| `route.py` exit 1 | Unknown issue type or not found | `grava show <id> --json` to inspect |
| `route.py` exit 2 | grava command failed | Check grava DB initialised in repo |
| `fix_bug_claim.py` / `epic_task_claim.py` exit 1 | Wrong issue type | Verify with `grava show <id> --json` |
| `fix_bug_claim.py` / `epic_task_claim.py` exit 2 | `grava claim` failed | Another agent may have claimed; check status |
| `fix_bug_claim.py` / `epic_task_claim.py` exit 3 | **HARD REJECT** — unresolved blockers | Skip-not-halt: batch loop / daemon move to next issue. Inspect with `grava blocked <id> --json`; close or remove blockers, then retry. No override. |
| `fix_bug_verify.py` exit 5 | Tests fail, retry N of 2 | Fix failing checks in worktree, re-run |
| `fix_bug_verify.py` exit 2 | Tests fail, max retries | Labeled `needs-human`; manual intervention required |
| `fix_bug_pr.py` exit 1 | Self-verify not passed | Run `fix_bug_verify.py` first |
| `fix_bug_pr.py` exit 2 | Push conflict or gh failed | Rebase worktree onto main, re-run |
| `qa_report.py` exit 1 | Results file missing/malformed | Claude must write `.grava/qa-<id>-results.json` first |
| `task_gen_expand.py` exit 1 | No `tg:src:` label on epic | Epic not created by task-generator, or label removed |
| `task_gen_expand.py` exit 2 | Operator declined | Re-invoke to approve |
| `pick_ready.py` returns `[]` | No ready issues for team | Backlog empty or all issues in-progress |
| `grava wisp read` exit 1 | Key missing (not an error) | Treat as "not set" — use empty string default |
