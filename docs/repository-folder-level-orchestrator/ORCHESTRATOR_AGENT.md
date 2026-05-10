# Orchestrator Agent

Routes grava issues to specialized agent teams based on issue type, manages concurrency, and tracks cross-team status.

---

## Architecture

```
                         ┌──────────────┐
                         │ Orchestrator │
                         │   /deploy    │
                         └──────┬───────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                  │
              ▼                 ▼                  ▼
     ┌────────────────┐ ┌──────────────┐  ┌───────────────┐
     │ Epic/Task Team │ │ Fix-Bug Team │  │   QA Team     │
     │  (existing)    │ │              │  │               │
     │                │ │ claim → fix  │  │ checklist →   │
     │ /ship, /plan,  │ │ → verify →  │  │ review →      │
     │ /hunt          │ │ PR → watch   │  │ report        │
     └────────────────┘ └──────────────┘  └───────────────┘
```

## Entry Point

```bash
/deploy                     # auto-pick next ready issue, route to correct team
/deploy <id>                # route a specific issue
/deploy --team fix-bug      # only pick from bugs
/deploy --team qa           # only pick QA-eligible issues
/deploy --parallel          # fill all idle team slots
```

---

## Routing Logic

The orchestrator reads issue metadata and routes:

```
issue = grava show <id> --json

if issue.type == "bug":
    → fix-bug-team

elif issue.type in ["task", "story", "subtask"]:
    → epic/task-team  (existing /ship pipeline)

elif issue.labels contains "qa-ready":
    → qa-team
```

### Routing Table

| Issue type | Label filter       | Team          | Entry command         |
|------------|--------------------|---------------|-----------------------|
| `bug`      | —                  | fix-bug-team  | `/deploy <id>`        |
| `task`     | —                  | epic/task-team| `/ship <id>`          |
| `story`    | —                  | epic/task-team| `/ship <id>`          |
| `bug`/`task`/`story` | `qa-ready` | qa-team    | `/deploy <id> --team qa` |

### Priority within teams

```bash
# Orchestrator picks the highest-priority ready issue per team:
grava ready --type bug --limit 1          # fix-bug-team candidate
grava ready --type task,story --limit 1   # epic/task-team candidate
grava ready --label qa-ready --limit 1    # qa-team candidate
```

---

## Fix-Bug Team

### Pipeline

```
Backlog → /deploy → [claimer] → [fixer] → [self-verifier] → [pr-creator] → PR → watcher → done
```

### Phases

#### Phase 0: Claim

1. Validate `issue.type == "bug"`
2. Run `grava claim <id>` → provisions worktree `.worktree/grava-<id>/` on branch `grava/grava-<id>`
3. Set `pipeline_phase=claimed`, `team=fix-bug`
4. Read bug description, reproduction steps, and any attached logs/traces

#### Phase 1: Fix

The fixer agent:

1. **Reproduce** — write or run a failing test that demonstrates the bug
   ```
   step: reproduce → failing-test-written
   ```
2. **Root-cause** — trace from the symptom to the root cause; leave a `## Root Cause` comment on the issue
   ```
   step: root-cause → cause-identified
   ```
3. **Fix** — apply the minimal change that resolves the root cause
   ```
   step: fix → fix-applied
   ```
4. **Regression guard** — ensure the failing test now passes; add edge-case tests if warranted
   ```
   step: regression → tests-green
   ```

Commits use: `fix(<scope>): <description> (grava-<id>)`

#### Phase 2: Self-Verify

Unlike the epic/task team's external reviewer, the fix-bug team does a lighter **self-verification**:

1. Run full test suite (`go test ./...`)
2. Run linter (`golangci-lint run ./...`)
3. Run `go build ./...`
4. Verify the original reproduction case passes
5. Check no unrelated tests broke (diff test results against baseline)

Verdict:
- **PASS** → label `self-verified`, proceed to PR
- **FAIL** → loop back to Phase 1 (max 2 retries), then `needs-human`

#### Phase 3: Create PR

Same as epic/task team's Phase 3:

1. Run `scripts/pre-merge-check.sh`
2. Push branch, `gh pr create`
3. Write `pr_url`, `pr_number` wisps
4. Label `pr-created`
5. Set `pipeline_phase=pr_created`

#### Phase 4: Handoff + Concurrency

**Key difference from epic/task team:** after PR creation, the orchestrator **immediately releases the fix-bug slot** and can start another bug fix in a parallel terminal.

```
Terminal 1: /deploy grava-bug-001  → PR created, watcher armed → slot freed
Terminal 2: /deploy grava-bug-002  → starts while bug-001 PR is open
```

The `pr-merge-watcher.sh` (same cron, shared with epic/task team) handles:
- **PR merged** → `grava close`, `pipeline_phase=complete`
- **PR comments** → writes `pr_new_comments` wisp, re-entry on next `/deploy <id>`
- **PR closed** → sets `pipeline_phase=failed`, labels `pr-rejected`

### Re-entry on PR Comments

```bash
/deploy grava-bug-001
# → detects pr_new_comments wisp
# → spawns fixer agent to address comments
# → pushes, clears wisp, re-arms watcher
```

### Wisps (fix-bug-specific)

| Key | Written by | Meaning |
|-----|-----------|---------|
| `team` | orchestrator | `fix-bug` |
| `step` | fixer | `reproduce`, `root-cause`, `fix`, `regression`, `self-verify` |
| `root_cause` | fixer | Markdown summary of root cause |
| `reproduction_test` | fixer | Path to the reproduction test file |
| `self_verify_result` | verifier | `pass` / `fail` |
| `self_verify_retries` | verifier | Retry count (cap: 2) |

---

## QA Team

### Pipeline

```
Trigger → [checklist-loader] → [reviewer] → [report-generator] → report artifact
```

### When to trigger

QA is triggered when:
- An issue or PR is labeled `qa-ready`
- The orchestrator is invoked with `--team qa`
- A `/qa <id>` command is used directly

### Phase 0: Load Checklist

The QA team supports multiple checklist sources:

```bash
# From a local markdown file
/qa grava-abc123 --checklist docs/qa/cli-checklist.md

# From a Plane project (if Plane MCP is connected)
/qa grava-abc123 --checklist plane://project/QA/cycle/sprint-12

# Auto-detect: reads the issue's `qa_checklist` wisp or falls back to default
/qa grava-abc123
```

**Default checklist resolution order:**
1. `qa_checklist` wisp on the issue → path or URL
2. Parent epic's `qa_checklist` field
3. `docs/qa/default-checklist.md` in repo root

#### Checklist Format (Markdown)

```markdown
# QA Checklist — CLI Commands

## Functional
- [ ] Command executes without error on valid input
- [ ] Command returns non-zero exit code on invalid input
- [ ] Help text is accurate and complete (`--help`)
- [ ] All documented flags work as described
- [ ] Output format matches spec (JSON, table, plain)

## Error Handling
- [ ] Meaningful error messages on bad input
- [ ] No stack traces leaked to user
- [ ] Graceful handling of network/DB unavailability

## Regression
- [ ] No existing tests broken
- [ ] Edge cases from bug history covered

## UX
- [ ] Output is human-readable in terminal
- [ ] Colors/formatting degrade gracefully without TTY
- [ ] Performance: completes within acceptable time
```

Checklists can be specialized per output type:

| Output type | Checklist template |
|-------------|-------------------|
| CLI commands | `docs/qa/cli-checklist.md` |
| REST API | `docs/qa/api-checklist.md` |
| Web UI/UX | `docs/qa/web-checklist.md` |
| Mobile | `docs/qa/mobile-checklist.md` |

### Phase 1: Review

The reviewer agent works through the checklist item by item:

1. **For CLI commands:**
   - Run the command in the worktree
   - Capture stdout, stderr, exit code
   - Compare against expected behavior from acceptance criteria

2. **For REST APIs:**
   - Send requests via `curl` or a test script
   - Validate response codes, body schema, headers
   - Check error responses

3. **For Web UI/UX:**
   - If a URL is provided, fetch and analyze with accessibility/structure checks
   - If screenshots are attached, analyze visually
   - Cross-reference against design spec if available

4. **For Mobile:**
   - Review against screenshots or screen recordings attached to the issue
   - Check against platform-specific guidelines (if provided)

Each checklist item gets a verdict:

```
✅ PASS  — meets criteria
❌ FAIL  — does not meet criteria (with evidence)
⚠️ WARN  — partially meets criteria or needs human judgment
⏭️ SKIP  — not applicable to this issue
```

### Phase 2: Generate Report

The report-generator produces a structured QA report:

```markdown
# QA Report — grava-abc123

**Issue:** Add rate limiting to /api/export
**Reviewed by:** qa-agent
**Date:** 2026-05-05
**Checklist:** docs/qa/api-checklist.md
**Verdict:** ❌ FAIL (8/10 pass, 1 fail, 1 warn)

## Results

### Functional (5/5 ✅)
- ✅ Endpoint returns 200 on valid request
- ✅ Rate limit triggers at 100 req/min
- ✅ 429 response includes Retry-After header
- ✅ Different users have independent limits
- ✅ Limit resets after window expires

### Error Handling (2/3 — 1 ❌)
- ✅ Returns 429 with clear message
- ❌ **Missing error body on 429** — response body is empty,
     expected JSON `{"error": "rate_limited", "retry_after": N}`
     Evidence: `curl -v ...` → empty body
- ✅ Graceful handling when Redis unavailable (falls back to in-memory)

### Regression (1/2 — 1 ⚠️)
- ✅ Existing export tests pass
- ⚠️ No test for the exact boundary (99th vs 100th request)
     Recommend adding boundary test

## Blocking Issues
1. Empty response body on 429 — must fix before merge

## Recommendations
1. Add boundary test at exactly 100 requests
2. Consider adding `X-RateLimit-Remaining` header
```

### Report Delivery

The report is:
1. Written as a comment on the grava issue (`grava comment <id> --file qa-report.md`)
2. Saved to `docs/qa/reports/grava-<id>-qa-report.md`
3. If the verdict is FAIL, the issue is labeled `qa-failed` and status stays `in_progress`
4. If the verdict is PASS, the issue is labeled `qa-passed`

### Wisps (QA-specific)

| Key | Written by | Meaning |
|-----|-----------|---------|
| `team` | orchestrator | `qa` |
| `qa_checklist` | orchestrator or issue author | Path to checklist file |
| `qa_verdict` | report-generator | `pass` / `fail` / `warn` |
| `qa_report_path` | report-generator | Path to saved report |
| `qa_fail_count` | report-generator | Number of failed items |
| `qa_blocking_items` | report-generator | JSON array of blocking failures |

---

## Orchestrator State Machine

```
                    ┌──────────────────────────────────┐
                    │         ORCHESTRATOR              │
                    │                                   │
  /deploy ─────►   │  1. grava ready --json             │
                    │  2. Read issue type + labels       │
                    │  3. Route to team                  │
                    │  4. Write team wisp                │
                    │  5. Spawn team pipeline            │
                    │                                   │
                    │  On completion:                    │
                    │    epic/task: pipeline_phase=complete │
                    │    fix-bug:   pipeline_phase=complete │
                    │    qa:        qa_verdict written    │
                    └──────────────────────────────────┘
```

### Orchestrator Wisps

| Key | Meaning |
|-----|---------|
| `team` | Which team owns this issue: `epic-task`, `fix-bug`, `qa` |
| `pipeline_phase` | Shared across all teams |
| `orchestrator_heartbeat` | Unix timestamp, flagged by `grava doctor` if >30min stale |

### Concurrency Model

```
Slot 1 (epic/task):  /ship grava-task-001         ← long-running, blocks slot
Slot 2 (fix-bug):    /deploy grava-bug-001        ← PR created, slot freed
Slot 3 (fix-bug):    /deploy grava-bug-002        ← starts after bug-001 PR
Slot 4 (qa):         /qa grava-task-002           ← independent, read-only
```

Rules:
- **Epic/task team:** 1 issue at a time (uses worktree, review rounds are heavyweight)
- **Fix-bug team:** up to N concurrent (configurable, default 2), slot freed after PR creation
- **QA team:** unlimited concurrency (read-only, no worktree mutation)
- **Cross-team:** QA can run on an issue while fix-bug works on a different one

---

## Commands Reference

```
ORCHESTRATOR
  /deploy                      Auto-pick + route to correct team
  /deploy <id>                 Route specific issue
  /deploy --team fix-bug       Only pick bugs
  /deploy --team qa            Only pick qa-ready issues
  /deploy --parallel           Fill all idle team slots

FIX-BUG TEAM
  /deploy <bug-id>             Claim + fix + verify + PR
  /deploy <bug-id> --retry     Re-fix after PR rejection
  /deploy <bug-id> --skip-verify   Skip self-verification (use with caution)

QA TEAM
  /qa <id>                     Run QA against default checklist
  /qa <id> --checklist <path>  Run QA against specific checklist
  /qa <id> --type cli|api|web|mobile   Use type-specific default checklist
  /qa --batch <label>          Run QA on all issues with label

MONITORING
  grava list --team fix-bug             All fix-bug issues
  grava list --team qa                  All QA issues
  grava list --label qa-failed          Failed QA
  grava list --label self-verified      Bugs awaiting PR merge
  grava doctor                          Health check (all teams)
```

---

## Checklist Templates

Create these files to bootstrap QA:

```
docs/qa/
├── cli-checklist.md
├── api-checklist.md
├── web-checklist.md
├── mobile-checklist.md
├── default-checklist.md
└── reports/
    └── .gitkeep
```

---

## Integration with Existing Pipeline

The orchestrator wraps the existing `/ship` pipeline — it doesn't replace it:

- `/ship` still works standalone for epic/task team
- `/deploy` on a `task`/`story` simply calls `/ship` internally
- `/deploy` on a `bug` invokes the fix-bug pipeline
- `/qa` invokes the QA pipeline independently

The `pr-merge-watcher.sh` cron is shared across epic/task and fix-bug teams — it reads the `team` wisp to determine which team's re-entry logic to apply.
