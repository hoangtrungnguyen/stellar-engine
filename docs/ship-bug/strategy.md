# /ship-bugfix — Strategy

**Status:** Draft · **Last updated:** 2026-05-13

> Grounded in the existing `agents/orchestrator/` implementation on `main` (untracked at time of writing). The pipeline described below is the one already implemented; this document captures intent and rules around it rather than proposing a different design.

---

## 1. Problem

The default `/ship` pipeline (coder → reviewer → pr-creator) targets task-shaped work: a spec defines the target behavior, AC defines done. Bugs are different:

- The bug report describes a **symptom**, not the target behavior.
- The precondition is **reproduction**, not specification.
- A fix must demonstrably resolve the reported case **and not regress neighbors**.
- "Cannot reproduce" is a valid outcome that should halt the pipeline cleanly, not waste a coder turn.

Forcing bugs through `/ship` either skips confirmation (risk: fix the wrong thing) or bloats `/ship` with bug branching (risk: violates its one-issue-one-PR shape). Stellar Engine's `team_routing.bug` exists to route bug-type issues to a dedicated pipeline. This document defines that pipeline: **fix-bug**.

---

## 2. Thesis

`/ship-bugfix` is a **five-phase, single-agent pipeline orchestrated by stateless CLI scripts and persisted through grava wisps**. The orchestrator agent (Claude) does the actual code work inside a worktree; the CLI scripts handle claim, verify, PR creation, and re-entry transitions.

```
Phase 0 (claim)    fix_bug_claim.py        → provisions .worktree/<id>/, sets pipeline_phase=claimed
Phase 1 (fix)      Claude in worktree      → reproduce → root-cause → fix → regression-guard
Phase 2 (verify)   fix_bug_verify.py       → go test + golangci-lint + go build, retry ≤2
Phase 3 (PR)       fix_bug_pr.py           → push branch + gh pr create + emit PR_CREATED
Phase 4 (re-entry) /deploy <id> [--retry]  → handle new PR comments or retry on failure
```

No internal reviewer agent. No separate confirmer agent. The "reproduce" step is a substep of Phase 1, executed by the same Claude session that produces the fix.

The skill emits the same signals as `/ship` (`CODER_DONE`, `PR_CREATED`, …) so the Stellar orchestrator parses output identically.

---

## 3. Components

### 3.1 CLI primitives (built; in `agents/orchestrator/cli/`)

| Script | Phase | Exit codes | Effect |
|:---|:---|:---|:---|
| `route.py` | pre-claim | 0 routed / 1 unroutable / 2 grava error | Reads issue type + labels; emits `{id, team, type, labels}`. `bug` type → `fix-bug`. Writes `team` wisp. |
| `pick_ready.py` | pre-claim | 0 | Returns `[]` of ready bugs, highest priority first. |
| `fix_bug_claim.py` | 0 | 0 claimed / 1 wrong type / 2 grava claim failed | Provisions `.worktree/<id>/` on branch `grava/<id>`. Idempotent if `pipeline_phase` already at `claimed` or later. Writes wisps: `team=fix-bug`, `pipeline_phase=claimed`, `orchestrator_heartbeat`. Emits `ISSUE_CLAIMED` signal. |
| `fix_bug_verify.py` | 2 | 0 pass / 5 retry-available / 2 max-retries-exceeded | Runs `go test ./...`, `golangci-lint run ./...` (skipped gracefully if not installed), `go build ./...` inside worktree. Writes wisps `self_verify_result`, `self_verify_retries` (cap 2). On pass: label `self-verified`, `pipeline_phase=coding_complete`, emit `CODER_DONE`. On max-retries: label `needs-human`. Checkpoints to `.grava/fix-bug-<id>-verify.json`. |
| `fix_bug_pr.py` | 3 | 0 created / 1 preconditions unmet / 2 push or gh failed | Verifies `pipeline_phase=coding_complete` AND `self_verify_result=pass`. Optionally runs `scripts/pre-merge-check.sh`. Pushes `grava/<id>` to origin. Runs `gh pr create` with title `fix: <issue_title> (<id>)` and body citing issue. Writes wisps `pr_url`, `pr_number`, `pr_awaiting_merge_since`, `pipeline_phase=pr_created`. Emits `PR_CREATED`. Idempotent. |
| `pr_merge_watcher.sh` (in `scripts/`) | post-PR | — | Polls open PRs, writes `pr_new_comments` wisp when reviewers comment, fires re-entry. |

### 3.2 Fix phase (Phase 1) — Claude in worktree

Phase 1 has no dedicated script. The orchestrator agent enters `.worktree/<id>/`, reads the issue, and runs four substeps end-to-end:

1. **Reproduce.** Write or run a failing test that demonstrates the bug. Commit: `reproduce(<scope>): failing test for <id>`. Wisp `step=reproduce`.
2. **Root-cause.** Trace symptom → cause. Post grava comment `## Root Cause\n<summary>`. Wisp `root_cause=<summary>`, `step=root-cause`.
3. **Fix.** Apply the minimal change that resolves the root cause. Commit: `fix(<scope>): <description> (<id>)`. Wisp `step=fix`.
4. **Regression guard.** Confirm the failing test now passes; add edge-case tests if relevant. Wisp `step=regression`.

Each substep refreshes `orchestrator_heartbeat`. Stale heartbeat (>30 min) flags the run for operator attention.

Heuristic for "scope" in commit messages and test placement: the smallest module that contains the failing behavior. The fix substep never touches code outside that scope without a written justification in the root-cause comment.

### 3.3 State machine (wisps)

Wisps persist phase transitions in grava so that any agent — including a re-entered Claude session — can pick up where the last one left off.

| Wisp | Owner | Values |
|:---|:---|:---|
| `team` | `route.py` | `fix-bug`, `epic-task`, `qa`, `task-generator` |
| `pipeline_phase` | scripts | `claimed`, `coding_complete`, `pr_created`, `pr_awaiting_merge`, `complete`, `failed` |
| `step` | Claude (fix phase) | `reproduce`, `root-cause`, `fix`, `regression` |
| `root_cause` | Claude | Markdown summary |
| `self_verify_result` | `fix_bug_verify.py` | `pass`, `fail` |
| `self_verify_retries` | `fix_bug_verify.py` | `0`, `1`, `2` (cap) |
| `pr_url`, `pr_number`, `pr_awaiting_merge_since` | `fix_bug_pr.py` | strings / timestamp |
| `pr_new_comments`, `pr_last_seen_comment_id` | `pr_merge_watcher` | JSON / ID |
| `orchestrator_heartbeat` | all | Unix ts; stale >30 min |

The full wisp inventory lives in [`agents/orchestrator/AGENT.md`](../../agents/orchestrator/AGENT.md) §Orchestrator Wisps.

### 3.4 Concurrency

| Team | Max concurrent | Slot freed at |
|:---|:---|:---|
| `task-generator` | 1 | task-generator Phase C done |
| `epic-task` | 1 | PR merged (watcher signals) |
| `fix-bug` | 2 (default) | Phase 3 (PR created) |
| `qa` | unlimited | Report posted |

Slot is freed at Phase 3, not at merge. This intentionally lets the next bug start while a PR awaits human review.

---

## 4. Principles

1. **Reproduce first, fix second.** The failing test exists as a git commit before any production code changes.
2. **CLI scripts own state transitions; Claude owns code.** Scripts are stateless and idempotent. Wisps are the source of truth.
3. **Reuse over reinvention.** Phase 3 (PR) mirrors what `/ship`'s pr-creator does. Signal contract is identical.
4. **Bounded retry.** Verify cap is 2. On failure beyond cap, label `needs-human` and stop — never auto-bypass.
5. **Halt loud on no-repro.** A coder running on an unreproducible bug produces a plausible-looking fix to a non-problem. Better surface to a human.
6. **Worktree-only writes.** `git push` and `gh pr create` only execute from the worktree branch `grava/<id>`. The orchestrator never writes to `main` directly.
7. **Free the slot at PR, not at merge.** Async PR review must not block fleet throughput. Watcher handles the long tail.

---

## 5. Success Criteria

| Dimension | Goal |
|:---|:---|
| Pipeline completion | ≥90% of claimed bugs reach `pr_created` without operator intervention |
| Verify pass rate | ≥70% on first attempt; ≥90% by attempt 2 (within retry cap) |
| Repro discipline | 100% of fix commits preceded by a `reproduce(...)` commit in the same branch |
| Throughput | Median claim → PR latency ≤30 min |
| Stale rate | <5% of runs flagged stale (>30 min without heartbeat) |
| Re-entry correctness | 100% of `pipeline_phase=pr_created` re-entries handle `pr_new_comments` correctly |

---

## 6. Non-Goals

- Bug filing — owned by `bug-hunter` and `/hunt`.
- Triage and prioritization — owned by `planner`.
- Root-cause analysis spanning multiple issues.
- Post-merge regression watch — owned by `pr_merge_watcher.sh` and downstream of this pipeline.
- An internal reviewer agent — deliberately omitted (see D1).
- Multi-agent orchestration inside fix-bug — one Claude session per claimed bug.
- Hotfix bypass — bugs still go through PR + human review.

---

## 7. Phased Rollout

Done in `main` (untracked in `agents/orchestrator/`):

| Phase | Outcome | Status |
|:---|:---|:---|
| 1 | `route.py`, `pick_ready.py` | ✅ |
| 2 | `fix_bug_claim.py` (claim + worktree provisioning + idempotency) | ✅ |
| 3 | `fix_bug_verify.py` (Go test/lint/build + retry cap + needs-human) | ✅ |
| 4 | `fix_bug_pr.py` (push + gh pr create + signals) | ✅ |
| 5 | `pr_merge_watcher.sh` and re-entry on `pr_new_comments` | ✅ |
| 6 | `orchestrator/AGENT.md` describing all of the above | ✅ |

Outstanding (see plan.md):

| Phase | Outcome | Status |
|:---|:---|:---|
| 7 | Commit `agents/orchestrator/` to main | ⬜ |
| 8 | Tests in `agents/orchestrator/tests/` | ⬜ |
| 9 | Non-Go verify backends (pluggable test runner) | ⬜ |
| 10 | Stellar Engine `team_routing.bug: ship-bugfix` wiring (Stellar plan Phase 4) | ⬜ |

---

## 8. Risks & Mitigations

| Risk | Mitigation |
|:---|:---|
| Claude skips the reproduce substep and goes straight to fix | Fix phase has explicit ordering in `AGENT.md`; commit-history check at PR time could enforce a `reproduce(...)` commit precedes the `fix(...)` commit (not yet implemented) |
| Verify is Go-only | Pluggable runner per-repo (see plan.md gap 3) |
| Coder over-fixes — touches unrelated files | No mechanical guard today; mitigated by PR review |
| Repro test is flaky | Verify runs `go test` once; flake escapes to PR. Run-thrice flake guard is a hardening item |
| Repro requires destructive setup (drop DB, etc.) | Confirmer halts with operator-visible note; never auto-destroys |
| Bug report ambiguous | Claude posts a clarification grava comment and halts; operator unblocks |
| Multiple agents try to claim same issue | `grava claim` enforces single-claimant at DB level; `fix_bug_claim.py` exits 2 on race |
| Worktree drift (someone hand-edits `.worktree/<id>/`) | Pre-merge check (optional script) can detect; otherwise PR review |
| `gh pr create` flakes (network, rate limit) | Exit 2; operator re-runs `fix_bug_pr.py` (idempotent via `pipeline_phase=pr_created` check) |

---

## 9. Decision Log

**D1: No internal reviewer agent.** The default `/ship` runs up to 3 reviewer rounds. `/ship-bugfix` skips this and relies on GitHub PR review. Trade-off: speed and lower token cost vs. one less internal gate. The reproduce-first invariant gives the human reviewer a precise focus point.

**D2: CLI scripts are stateless; wisps are state.** Scripts can be re-run; they read wisps to decide whether work is already done. This makes the pipeline crash-recoverable: kill any process and re-invoke from the orchestrator — it picks up at the right phase.

**D3: One Claude session per bug, not a multi-agent team.** The fix phase is small enough that splitting into confirmer/coder agents would add hand-off cost without adding gate value. The substeps (reproduce → root-cause → fix → regression) are sequential and rarely need parallelism.

**D4: Verify retries cap at 2.** Beyond 2 attempts, the issue is structurally bigger than the pipeline assumes. Label `needs-human` and stop.

**D5: Slot freed at PR creation, not at merge.** Fleet throughput would collapse if a single PR stuck in review held the slot. Watcher tracks merge async.

**D6: Verify is currently Go-specific.** Hard-coded `go test`, `golangci-lint`, `go build`. Adequate for the bootstrap target repo. Pluggable runner is plan.md gap 3.

**D7: `qa-ready` label overrides type in `route.py`.** A bug-type issue with `qa-ready` routes to QA, not fix-bug. This allows operators to short-circuit a bug into QA-verification without re-typing the issue.

---

## 10. Open Questions

1. When Claude halts at `cannot_reproduce`, who acts next — operator, `planner`, or auto-close after N days?
2. Multi-repo bugs (symptom in frontend, cause in backend) — single fix-bug invocation, or split per repo?
3. Regression bugs (worked at commit X, broken at HEAD) — should the fix phase also run `git bisect`?
4. Performance bugs (slow, not broken) — write a benchmark with a threshold, or out of scope?
5. Security bugs — does `/ship-bugfix` apply, or is there a separate `/ship-cve` track?
6. Should `fix_bug_pr.py` block PR creation if no `reproduce(...)` commit is found in the branch history?

---

## 11. Anti-Strategy

`/ship-bugfix` is **not**:

- A fuzzer or security scanner (those file bugs; `/ship-bugfix` fixes them).
- A triage tool (the issue is claimed and typed by the time `/ship-bugfix` runs).
- A regression detector (CI's job).
- A code-review pipeline (no internal reviewer; human PR review covers).
- A hotfix bypass (still goes through PR + merge watcher).
- A general "code mode" — refactors and features go through `/ship` (`epic-task` team).
- A multi-agent team — explicitly single-agent by design (D3).

Boundary: **one claimed bug issue → one PR with a reproduce-commit and a fix-commit, gated by self-verify.** Past that line is someone else's problem.
