# /ship-bugfix — Implementation Plan

**Status:** Draft · **Last updated:** 2026-05-13

Companion to [`strategy.md`](strategy.md). Strategy describes intent and rules. This plan covers what is built, what is missing, and the concrete next steps to close the gap.

---

## 1. Context

`main` branch already contains a working fix-bug pipeline at `agents/orchestrator/` — but the directory is **untracked** (`git status` shows `agents/orchestrator/` under untracked files). The code runs locally, but is not yet versioned, tested, or wired into Stellar Engine's `team_routing`. This plan closes those gaps.

The strategy document treats the pipeline shape as fixed. This plan does **not** propose redesign — only formalization.

---

## 2. What is built today

| Path | Lines | Purpose |
|:---|:---|:---|
| `agents/orchestrator/AGENT.md` | 399 | Full pipeline spec: routing, phases, wisps, hard limits, failure modes |
| `agents/orchestrator/cli/route.py` | 67 | Type/label → team mapping; writes `team` wisp |
| `agents/orchestrator/cli/pick_ready.py` | — | Ready-backlog probe per team |
| `agents/orchestrator/cli/fix_bug_claim.py` | 113 | Phase 0; idempotent claim + worktree |
| `agents/orchestrator/cli/fix_bug_verify.py` | 170 | Phase 2; Go test/lint/build with retry cap 2 |
| `agents/orchestrator/cli/fix_bug_pr.py` | 173 | Phase 3; push + gh pr create + signals |
| `agents/orchestrator/cli/task_gen_expand.py` | — | Epic delegation to task-generator |
| `agents/orchestrator/cli/qa_load.py`, `qa_report.py` | — | QA team pipeline (separate from fix-bug) |
| `agents/orchestrator/scripts/pr_merge_watcher.sh` | — | Async PR merge tracking |
| `agents/orchestrator/templates/qa/*.md` | — | QA checklists (cli/api/web/mobile/default) |

Tests directory: `agents/task-generator/tests/` exists; `agents/orchestrator/tests/` does not.

---

## 3. Gaps

### G1. Directory not committed
`agents/orchestrator/` is untracked. Any restore from origin loses the entire fix-bug pipeline.

### G2. No tests
Zero coverage for `route.py`, `fix_bug_claim.py`, `fix_bug_verify.py`, `fix_bug_pr.py`. Compare to `agents/task-generator/tests/` (10+ test files). Regressions in any of these scripts have no safety net.

### G3. Verify is Go-only
`fix_bug_verify.py` hard-codes `go test ./...`, `golangci-lint run ./...`, `go build ./...`. Will fail on any non-Go target repo (Python, TS, Rust, …). Stellar Engine's `repos.yaml` will register repos of mixed stacks; verify must adapt.

### G4. No `/ship-bugfix` skill file
Stellar's plan ([§5.2 in `stellar-engine-plan.md`](../../../../../../Desktop/files/stellar-engine-plan.md)) expects a callable skill `/ship-bugfix` that the stellar-orchestrator can invoke with an issue ID and parse output for `PR_CREATED` / `PIPELINE_HALTED` / `PIPELINE_FAILED`. Today, the fix-bug pipeline is invoked via the orchestrator's `/deploy <id>` command path, which routes internally. There is no standalone `/ship-bugfix` skill that the Stellar orchestrator can call as one of its `team_routing` targets.

### G5. No reproduce-commit enforcement
`fix_bug_pr.py` does not check that a `reproduce(...)` commit precedes the `fix(...)` commit. The reproduce-first invariant (strategy §4 principle 1) is unenforced.

### G6. No flake guard on verify
`fix_bug_verify.py` runs `go test` once. A flaky test that passes on retry will let a non-fix slip through. Strategy §8 risks this; verify does not mitigate.

### G7. Watcher → fix-bug re-entry is manual
`pr_merge_watcher.sh` writes `pr_new_comments`, but a human must run `/deploy <id>` to trigger Claude to address those comments. The Stellar orchestrator would close this loop automatically; the current setup does not.

### G8. Pre-merge check is optional and repo-local
`fix_bug_pr.py` runs `scripts/pre-merge-check.sh` if present. No documentation; no default. Discoverability is poor.

---

## 4. Plan

### Phase A — Foundation (do first, before any new feature)

**A1. Commit `agents/orchestrator/` to main.**
- Path: `agents/orchestrator/` (recursive)
- Action: `git add agents/orchestrator/ && git commit -m "Add fix-bug + QA orchestrator scripts"`
- Verify: `git status` shows clean; `git log --oneline -1` reflects the new commit.
- Note: include or exclude `__pycache__/` per existing `.gitignore` policy (`agents/task-generator/__pycache__/` is in `.git` already — match its handling).

**A2. Add `agents/orchestrator/tests/`.**
- Files to create:
  - `agents/orchestrator/tests/__init__.py`
  - `agents/orchestrator/tests/test_route.py` — covers bug, task, story, epic, qa-ready-override, unroutable, grava-error paths.
  - `agents/orchestrator/tests/test_fix_bug_claim.py` — covers wrong-type rejection, idempotency, grava-claim-failure.
  - `agents/orchestrator/tests/test_fix_bug_verify.py` — covers pass, fail-with-retry-available, fail-max-retries, `--skip-verify`, missing-worktree.
  - `agents/orchestrator/tests/test_fix_bug_pr.py` — covers preconditions-unmet, idempotency on `pr_created`, push-failure, gh-failure, success path.
- Reuse `agents/task-generator/tests/` style: mock `subprocess.run` via fixtures.

**A3. Update root `CLAUDE.md` to point to `agents/orchestrator/AGENT.md`.**
- Path: `CLAUDE.md` (project instructions)
- Action: add a "Sub-agents" section listing `agents/task-generator/` and `agents/orchestrator/` with one-line descriptions.

### Phase B — Pluggable verify (closes G3)

**B1. Extract verify backends.**
- New file: `agents/orchestrator/cli/verify_backends.py`
- Defines an interface `VerifyBackend` with methods `test()`, `lint()`, `build()` each returning `(ok: bool, output: str)`.
- Implementations: `GoBackend` (current behavior moved here), `PythonBackend` (`pytest`, `ruff check`, `python -m compileall`), `NodeBackend` (`npm test`, `npm run lint`, `npm run build` — gated on presence of those scripts in `package.json`).

**B2. Add per-repo verify config to `repos.yaml` / `repo-map.yaml`.**
- New keys per project entry:
  ```yaml
  verify_backend: go        # go | python | node | none
  verify_commands:          # optional overrides
    test:  "make test"
    lint:  "make lint"
    build: "make build"
  ```
- `fix_bug_verify.py` reads target-repo's config, instantiates backend, runs checks.

**B3. Fall back to `none` if config absent.**
- `verify_backend: none` skips all checks (equivalent to today's `--skip-verify`) but logs a warning. Use only for repos still on manual verify.

**B4. Tests for `verify_backends.py`.**
- Mock `subprocess.run`; assert backend dispatches correct commands.

### Phase C — `/ship-bugfix` skill (closes G4)

**C1. Author `/ship-bugfix` skill in the target repo's `.claude/skills/`.**
- Per Stellar plan: each managed repo owns its own `/ship-bugfix` skill. The skill is a thin shim that:
  1. Accepts `$ISSUE_ID` as first arg.
  2. Runs `python3 agents/orchestrator/cli/route.py "$ISSUE_ID"` and verifies team is `fix-bug`. Halt `PIPELINE_HALTED: wrong_team` otherwise.
  3. Runs `python3 agents/orchestrator/cli/fix_bug_claim.py "$ISSUE_ID"`. On exit 1/2 → emit `PIPELINE_HALTED: <reason>`.
  4. Hands off to Claude in worktree for Phase 1 (fix substeps).
  5. Runs `python3 agents/orchestrator/cli/fix_bug_verify.py "$ISSUE_ID"`. On exit 5 → loop back to Phase 1 (retry); on exit 2 → emit `PIPELINE_FAILED: max_retries`; on exit 0 → continue.
  6. Runs `python3 agents/orchestrator/cli/fix_bug_pr.py "$ISSUE_ID"`. On exit 0 → emit `PR_CREATED: <url>`.
- Skill location in target repo: `.claude/skills/ship-bugfix/SKILL.md`.
- Skill must run from repo root (per Stellar plan §5.2 contract).

**C2. Wire `team_routing.bug: ship-bugfix` in Stellar `repos.yaml` once C1 lands in at least one target repo.**

### Phase D — Hardening (closes G5–G8)

**D1. Reproduce-commit enforcement (G5).**
- In `fix_bug_pr.py`, after Phase 3 step 4 (push), check branch history:
  ```python
  log = subprocess.run(["git", "log", "--format=%s", f"main..{branch}"], cwd=worktree, …)
  has_reproduce = any(line.startswith("reproduce(") for line in log.stdout.splitlines())
  has_fix = any(line.startswith("fix(") for line in log.stdout.splitlines())
  if not (has_reproduce and has_fix):
      exit(1)  # preconditions unmet — orchestrator emits PIPELINE_HALTED
  ```
- Add test for branch-without-reproduce → exit 1.

**D2. Flake guard on verify (G6).**
- In `fix_bug_verify.py`, change `go test` (or backend `test()`) to run 3× back-to-back; require all 3 passes.
- Add `--flake-runs N` CLI flag (default 3) for tuning.

**D3. Automatic re-entry on PR comments (G7).**
- New script `agents/orchestrator/cli/handle_pr_comments.py` invoked by `pr_merge_watcher.sh` when `pr_new_comments` is non-empty.
- The script spawns Claude in the worktree to address comments, pushes, clears `pr_new_comments` wisp.
- Stellar orchestrator-side: when `/ship-bugfix` is invoked on an issue already at `pipeline_phase=pr_created`, route to this handler instead of re-running from claim.

**D4. Default pre-merge-check (G8).**
- Add `agents/orchestrator/templates/pre-merge-check.sh` — a sensible default (`make test || go test ./...`).
- Document in `agents/orchestrator/AGENT.md` that target repos may copy this template into `scripts/` to enable pre-merge validation.

---

## 5. Critical files to modify

| Phase | File | Action |
|:---|:---|:---|
| A1 | `agents/orchestrator/` (whole dir) | `git add` + commit |
| A2 | `agents/orchestrator/tests/*.py` | Create |
| A3 | `CLAUDE.md` (repo root) | Edit — add sub-agents section |
| B1 | `agents/orchestrator/cli/verify_backends.py` | Create |
| B1 | `agents/orchestrator/cli/fix_bug_verify.py` | Edit — dispatch to backend |
| B2 | `repo-map.yaml`, `systems/<Name>/system.yaml` | Edit — add `verify_backend` keys |
| B4 | `agents/orchestrator/tests/test_verify_backends.py` | Create |
| C1 | `<target-repo>/.claude/skills/ship-bugfix/SKILL.md` | Create (in each managed repo) |
| D1 | `agents/orchestrator/cli/fix_bug_pr.py` | Edit — add commit history check |
| D2 | `agents/orchestrator/cli/fix_bug_verify.py` | Edit — add flake loop |
| D3 | `agents/orchestrator/cli/handle_pr_comments.py` | Create |
| D3 | `agents/orchestrator/scripts/pr_merge_watcher.sh` | Edit — call handler |
| D4 | `agents/orchestrator/templates/pre-merge-check.sh` | Create |

---

## 6. Verification

**End-to-end test (after Phase A):**
1. Pick a real bug-type issue in a Go target repo with grava initialized.
2. Run `python3 agents/orchestrator/cli/fix_bug_claim.py <id> --target-repo <path>`.
3. Enter the worktree, write a failing test, commit `reproduce(...)`. Apply fix, commit `fix(...)`.
4. Run `python3 agents/orchestrator/cli/fix_bug_verify.py <id> --target-repo <path>` → expect exit 0.
5. Run `python3 agents/orchestrator/cli/fix_bug_pr.py <id> --target-repo <path>` → expect exit 0 + PR URL.
6. Confirm wisps: `grava wisp read <id> pipeline_phase` returns `pr_created`.

**End-to-end test (after Phase B, on a Python repo):**
- Repeat above with `verify_backend: python` in the repo's `system.yaml`. Verify dispatches `pytest`, `ruff check`, `python -m compileall`.

**End-to-end test (after Phase C, via Stellar):**
- With `team_routing.bug: ship-bugfix` in `repos.yaml`, run the stellar-orchestrator loop (once implemented) and observe a bug issue dispatched via `/ship-bugfix` and parsed back as `PR_CREATED`.

**Regression suite (continuous):**
- `cd agents/orchestrator && python3 -m pytest tests/` returns 0.
- Run after every edit to any `cli/*.py` script.

---

## 7. Sequencing and dependencies

```
A1 ─┬─> A2 ─┬─> B1 ─> B2 ─> B3 ─> B4 ─┬─> C1 ─> C2
    └─> A3                            └─> D1 / D2 / D4 (independent of C)
                                          D3 depends on C1 (skill must exist to call back into)
```

- **Block on A1.** Everything else depends on the directory existing in git.
- **B (verify backends) is independent of C (Stellar wiring).** Run in parallel if two operators are available.
- **D3 (auto re-entry) depends on C1.** The `/ship-bugfix` skill must exist before the watcher's handler can return into it.
- **D1, D2, D4 are independent quick wins** — can land anytime after A1.

---

## 8. Out of scope for this plan

- Multi-repo bugs (frontend/backend split) — strategy §10 OQ2.
- `git bisect` for regression bugs — strategy §10 OQ3.
- Performance bugs / benchmark gating — strategy §10 OQ4.
- Security-bug separate track — strategy §10 OQ5.
- Generator agent (Stellar §3.1) — different track entirely.
