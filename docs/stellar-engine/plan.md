# Stellar Engine — Implementation Plan

**Status:** Draft · **Last updated:** 2026-05-13

Companion to [`strategy.md`](strategy.md). Strategy describes intent and components. This plan covers what is built, what is missing, and the concrete sequencing to close the gap toward the fleet runtime.

---

## 1. Context

`main` has two sub-agents and a set of utilities. The `orchestrator/` directory is **untracked**. The `task-generator/` is committed and on Phase 6. The fleet runtime (`se` CLI, `stellar-orchestrator`, `repos.yaml`) and the Generator agent are unbuilt. This plan codifies the path from today's in-Claude orchestrator to a fleet runtime — without re-doing what already works.

The plan is grounded against three observed scale signals:

- **One target repo today.** No multi-repo coordination problem yet.
- **In-Claude routing works.** Operator-driven `/deploy` is acceptable at current volume.
- **Go-only verify.** First friction point against multi-repo expansion.

Phases are sized so that Phase N can be exercised on real workloads for a week before Phase N+1 starts. Phases inside a band may parallelize.

---

## 2. Inventory

### 2.1 Shipped (committed to main)

| Path | Lines | Function |
|:---|:---|:---|
| `agents/task-generator/AGENT.md` | 208 | Three-phase spec (preview / Plane / Grava) with Phase 4 reconciliation + Phase 5 dep analyzer + Phase 6 Plane relations |
| `agents/task-generator/parser.py` | — | HTML → Markdown → IR pipeline |
| `agents/task-generator/planner.py` | — | Topological reorder + reconciliation logic |
| `agents/task-generator/plane_client.py` | — | Plane REST surface |
| `agents/task-generator/plane_writer.py` | — | Phase B writes + `blocking` relations |
| `agents/task-generator/grava_writer.py` | — | Phase C mirror + `grava dep` |
| `agents/task-generator/dependency_analyzer.py` | — | Cycle detection + topological sort |
| `agents/task-generator/reconcile.py` | — | Sentinel-label diff against spec |
| `agents/task-generator/cli/*.py` | — | 9 CLI scripts: `run`, `fetch`, `preflight`, `parse`, `render`, `write`, `grava`, `init_run`, `resolve_repo` |
| `agents/task-generator/tests/*.py` | — | 10 test files: parser, planner, plane_writer, grava_writer, dependency_analyzer, reconcile, repo_map, plane_client, ir |
| `repo-map.yaml` | 40 | Plane project UUID → repo metadata |
| `systems/SportBuddies/*` | — | System spec template |
| `setup.sh` | — | Install plane CLI + Python deps + creds |
| `mcp-setup.md` | — | Plane MCP server connection guide |
| `upload_project_pages.py`, `upload_wiki_page.py` | — | Markdown → Plane sync utilities |

### 2.2 Built but untracked (P0 to commit)

| Path | Function |
|:---|:---|
| `agents/orchestrator/AGENT.md` (399 lines) | Full pipeline: routing, fix-bug, QA, task-generator delegation, wisp inventory, hard limits |
| `agents/orchestrator/cli/route.py` | Type/label → team mapping |
| `agents/orchestrator/cli/pick_ready.py` | Backlog probe per team |
| `agents/orchestrator/cli/fix_bug_claim.py` | Phase 0 claim |
| `agents/orchestrator/cli/fix_bug_verify.py` | Phase 2 verify (Go-only) |
| `agents/orchestrator/cli/fix_bug_pr.py` | Phase 3 PR creation |
| `agents/orchestrator/cli/qa_load.py` | QA Phase 0 checklist loader |
| `agents/orchestrator/cli/qa_report.py` | QA Phase 2 report generator |
| `agents/orchestrator/cli/task_gen_expand.py` | Bridge from grava epic → task-generator run |
| `agents/orchestrator/scripts/pr_merge_watcher.sh` | Cron PR lifecycle watcher |
| `agents/orchestrator/templates/qa/*.md` | 5 QA checklists (default + cli/api/web/mobile) |

### 2.3 Planned (this plan owns sequencing; sub-plans own detail)

| Component | Owner doc |
|:---|:---|
| `/ship-bugfix` standalone skill + pluggable verify | [`docs/ship-bug/plan.md`](../ship-bug/plan.md) |
| Grava → Plane state sync v0 | [`docs/grava-plane-status-sync-plan.md`](../grava-plane-status-sync-plan.md) |
| Self-host Plane | [`docs/self-host/self-host-plane-plan.md`](../self-host/self-host-plane-plan.md) |
| `se` CLI | this plan §4 Phase B |
| `stellar-orchestrator` agent | this plan §4 Phase D |
| Generator agent | this plan §4 Phase F |

---

## 3. Gaps

### G1. `orchestrator/` untracked
Loses on any clean clone. P0.

### G2. No tests for `orchestrator/cli/`
Zero coverage. `task-generator/tests/` is the contrast (10 files). Regressions in `route.py`, `fix_bug_*`, `qa_*` go undetected.

### G3. Verify is Go-only
`fix_bug_verify.py` hard-codes `go test`, `golangci-lint`, `go build`. Blocks multi-language fleet.

### G4. No standalone `/ship-bugfix`, `/ship-qa` skills
Today's entry path is `/deploy <id>` (orchestrator-internal routing). A future `stellar-orchestrator` agent (Phase D) needs callable skills with stable signal contracts that any Claude session can invoke.

### G5. No fleet runtime
No `se` CLI, no `stellar-orchestrator.md`, no `repos.yaml`, no `policies/default.yaml`. Operator drives everything by hand today.

### G6. No Generator
Spec markdown is hand-written into Plane pages. No agent generates specs from a knowledge source.

### G7. Stale top-level `CLAUDE.md`
Worktree `CLAUDE.md` describes `sync.py` (which does not exist) and Plane CLI tooling, not `agents/task-generator/` or `agents/orchestrator/`. Misleads new contributors.

### G8. Two registries with no cross-link
`repo-map.yaml` (Plane UUID → repo) exists. Future `repos.yaml` (repo name → runtime config) will be added. Without explicit comments operators will edit the wrong one.

### G9. `pr_merge_watcher.sh` is not wired by default
Operator must install the cron line manually. No `setup.sh` integration, no doctor check.

### G10. Plane sync (grava → Plane state) plan exists but is unbuilt
`sync_plane_status.py` is referenced in [`docs/grava-plane-status-sync-plan.md`](../grava-plane-status-sync-plan.md) but the file does not exist. The Plane client lacks `list_states()`.

---

## 4. Plan

### Phase A — Foundation (close G1, G2, G7, G9)

**A1. Commit `agents/orchestrator/`.**
- Path: `agents/orchestrator/` recursive (exclude `__pycache__/` per existing `.gitignore` policy).
- Action: `git add agents/orchestrator/ && git commit -m "Add orchestrator agent: route + fix-bug + QA pipelines"`.
- Verify: `git status` clean; clone-test on a fresh checkout shows the agent.

**A2. Tests for `orchestrator/cli/`.**
- Create `agents/orchestrator/tests/__init__.py` + one test file per CLI script.
- Mirror `task-generator/tests/` mocking style (subprocess.run patched via fixtures).
- Coverage minimum: every documented exit code path of every script.

**A3. Rewrite root `CLAUDE.md`.**
- Replace the `sync.py` narrative with an actual map of the repo: two sub-agents, where they live, what they do, how they're invoked, and where their docs live.
- Add a "Sub-agents" table linking `agents/task-generator/AGENT.md` and `agents/orchestrator/AGENT.md`.
- Keep the Plane CLI setup section but mark it as one of several setup paths.

**A4. Wire `pr_merge_watcher.sh` into setup.**
- Edit `setup.sh` to print the cron install snippet (`*/5 * * * * cd … && bash …/pr_merge_watcher.sh`) at the end of install.
- Add an `se doctor`-style check in a new `agents/orchestrator/cli/doctor.py` that verifies the cron line is installed (parse `crontab -l`).
- Document in `agents/orchestrator/AGENT.md` §Watcher Setup.

### Phase B — `se` CLI Phase 1 (read-only) — partial G5

**B1. Bootstrap CLI skeleton.**
- New: `cli/se` (Python entrypoint, `chmod +x`).
- Subcommands: `init`, `repos`, `doctor` (read-only).
- Args parsing: `argparse`. No external deps beyond `pyyaml` (already in `task-generator/requirements.txt`).
- Decision (reverses Stellar plan §9 D3): Python, not Go. Match the rest of the codebase. Re-evaluate at 5k LOC.

**B2. `se init`.**
- Scaffold `repos.yaml` (template with one commented example), `policies/default.yaml` (with documented keys), `logs/` directory.
- Idempotent: skip files that already exist; surface what was created.

**B3. `se repos`.**
- Parse `repos.yaml`. Output a table: NAME, PATH, MAX_CONCURRENT, PRIORITY_THRESHOLD, POLL_INTERVAL.
- Flag: `--json`.

**B4. `se doctor`.**
- Validate each repo entry in `repos.yaml`: path exists, contains `.grava/`, contains `.claude/skills/ship/` (or equivalent), passes `grava doctor`.
- Validate global tools: `tmux`, `grava`, `gh`, `claude` binaries available with version pin.
- Validate `pr_merge_watcher.sh` cron line for at least one repo (warning if missing on all).
- Exit code: 0 if all green, 1 if any error, 2 if any warning.

### Phase C — Skill exposure (close G4)

**C1. Author `/ship-bugfix` skill** in each managed target repo.
- Path in target repo: `.claude/skills/ship-bugfix/SKILL.md`.
- Body: wraps `agents/orchestrator/cli/fix_bug_{claim,verify,pr}.py` with phase ordering and signal emission. Defined in detail in [`docs/ship-bug/plan.md`](../ship-bug/plan.md) §C1.
- First target: the bootstrap Go repo.

**C2. Author `/ship-qa` skill** similarly.
- Wraps `agents/orchestrator/cli/qa_{load,report}.py` + Claude-in-worktree checklist execution.
- Signal contract: `QA_COMPLETE: <report_path>` on success, `PIPELINE_HALTED: <reason>` on hard fail.

**C3. Add signal contract reference doc.**
- New: `docs/signal-contract.md` listing every signal Stellar parses (`PR_CREATED`, `PIPELINE_HANDOFF`, `PIPELINE_INFO`, `PIPELINE_HALTED`, `PIPELINE_FAILED`, `QA_COMPLETE`, …) and which skill emits each.

### Phase D — `stellar-orchestrator` agent + lifecycle (close G5 mid)

**D1. Author `agents/stellar-orchestrator.md`.**
- Per-repo thin wrapper. Inputs via env vars: `STELLAR_REPO_NAME`, `STELLAR_REPO_PATH`, `STELLAR_POLL_INTERVAL`, etc.
- Loop: pause-check → nudge-check → probe `grava ready` → resolve `team_routing[type]` → invoke `/ship-bugfix` / `/ship-qa` / `/ship` → parse last-line signal → adaptive backoff.
- Concurrency cap: read from `repos.yaml`.

**D2. `se start <repo>` / `se stop <repo>` / `se attach <repo>`.**
- `start`: create `tmux:stella-<repo>`, export env, launch `stellar-orchestrator.md` in window 0.
- `stop`: write `logs/.paused.<repo>`, wait for in-flight to drain (cap at `ship_timeout_minutes`), kill tmux.
- `attach`: `tmux attach -t stella-<repo>`.
- Flag `--dry-run` for start: print the tmux commands without executing.

**D3. Update `agents/orchestrator/AGENT.md`.**
- Add §Fleet Wrapping: when invoked via `/deploy` directly, the agent uses `--target-repo`. When invoked via `stellar-orchestrator`, env vars supply the same.
- The in-Claude `/deploy` path remains for single-repo development.

### Phase E — Visibility + policy (close G5 end, G8)

**E1. `se status` / `se status --watch`.**
- Enumerate `stella-*` tmux sessions. Parse heartbeat files. Output: ORCH, UPTIME, IN_FLIGHT, READY, PR/HR.
- `--watch` re-renders every 5s.

**E2. `se teams [<repo>]`.**
- Read each repo's grava state. List issues with `pipeline_phase ∈ {claimed, coding_complete, pr_created}`.
- Output: REPO, ISSUE, TEAM, PHASE, STARTED.

**E3. `se logs <repo>` / `se pause <repo>` / `se resume <repo>` / `se nudge <repo>`.**
- `logs`: tail `logs/dispatch.jsonl`. Flags `-f`, `-n`, `--since`.
- `pause`/`resume`: touch/remove `logs/.paused.<repo>`.
- `nudge`: touch `logs/.nudge.<repo>`; stellar-orchestrator's 5s nudge-check consumes it.

**E4. `repos.yaml` cross-link annotation.**
- Add a top-of-file comment block explaining the distinction between `repo-map.yaml` (Plane UUID → repo) and `repos.yaml` (repo name → fleet runtime config). Same in `repo-map.yaml` pointing back.

**E5. `policies/default.yaml`.**
- Document keys: `global_max_concurrent`, `ship_timeout_minutes`, `pause_on_failure_streak`, `heartbeat.stale_threshold_minutes`, `heartbeat.check_interval_seconds`.
- Per-repo overrides in `policies/<repo>.yaml`.

### Phase F — Generator agent (close G6)

**F1. Choose initial input scope.**
- Decision needed (strategy §10 OQ3). Recommend: start with codebase + one URL/transcript. Avoid open-ended scope creep.

**F2. Author `agents/generator/AGENT.md`.**
- Inputs: knowledge source path, output directory.
- Outputs: markdown specs ready for `task-generator` consumption (epic / story / task hierarchy).
- Writes to `drafts/` (not directly to Plane). Operator promotes to `specs/` after review.

**F3. CLI scripts.**
- `agents/generator/cli/extract.py` — read source, produce structured outline.
- `agents/generator/cli/render.py` — outline → markdown spec files.

**F4. Wire to `task-generator`.**
- After F2 lands a draft, the operator runs `/generate <draft_path>` → uploads via `upload_project_pages.py` → kicks off `task-generator` Phase A.

### Phase G — Hardening (close G3 partial, G10, remaining)

**G1. Pluggable verify backends.** See [`docs/ship-bug/plan.md`](../ship-bug/plan.md) Phase B.

**G2. Grava → Plane state sync v0.** See [`docs/grava-plane-status-sync-plan.md`](../grava-plane-status-sync-plan.md). Ship the per-agent hook approach; defer watermark observer.

**G3. Crash recovery.**
- `stellar-orchestrator` reads its own `logs/dispatch.jsonl` on restart, identifies last in-flight issue, resumes from the appropriate wisp phase.

**G4. Cost tracking.**
- Parse `claude` token usage from `/ship*` output (if exposed). Aggregate per repo into `logs/cost.jsonl`.

**G5. Integration tests.**
- Spin up 3 fake repos with seeded grava DBs. Drive `se start --all`. Assert: one issue per repo ships to PR, all wisps consistent, no orphaned tmux sessions.

---

## 5. Critical files to create or modify

| Phase | Path | Action |
|:---|:---|:---|
| A1 | `agents/orchestrator/` (recursive) | `git add` + commit |
| A2 | `agents/orchestrator/tests/*.py` | Create |
| A3 | `CLAUDE.md` (repo root) | Rewrite |
| A4 | `setup.sh`, `agents/orchestrator/cli/doctor.py`, `agents/orchestrator/AGENT.md` | Edit / create |
| B1 | `cli/se` | Create |
| B2 | `cli/se` (init subcmd), `repos.yaml` template, `policies/default.yaml` template | Create |
| B3 | `cli/se` (repos subcmd) | Edit |
| B4 | `cli/se` (doctor subcmd) | Edit |
| C1 | `<target-repo>/.claude/skills/ship-bugfix/SKILL.md` | Create (per target repo) |
| C2 | `<target-repo>/.claude/skills/ship-qa/SKILL.md` | Create (per target repo) |
| C3 | `docs/signal-contract.md` | Create |
| D1 | `agents/stellar-orchestrator.md` | Create |
| D2 | `cli/se` (start/stop/attach subcmds) | Edit |
| D3 | `agents/orchestrator/AGENT.md` | Edit (Fleet Wrapping section) |
| E1–E3 | `cli/se` (status/teams/logs/pause/resume/nudge subcmds) | Edit |
| E4 | `repo-map.yaml`, `repos.yaml` | Annotate |
| E5 | `policies/default.yaml` | Populate |
| F1–F4 | `agents/generator/{AGENT.md,cli/*.py}` | Create |
| G1 | per ship-bug plan | — |
| G2 | per grava-plane-status-sync plan | — |
| G3 | `agents/stellar-orchestrator.md`, `cli/se` | Edit |
| G4 | `cli/se` | Edit |
| G5 | `tests/integration/` | Create |

---

## 6. Verification

**After Phase A:**
- `git ls-files agents/orchestrator/ | wc -l` ≥ 12.
- `python3 -m pytest agents/orchestrator/tests/` → 0 failures.
- A clone-test of `main` shows the orchestrator agent end-to-end.
- `bash setup.sh` prints cron install snippet.

**After Phase B:**
- `cli/se init` in a clean directory creates `repos.yaml` + `policies/default.yaml`.
- `cli/se repos` lists 0 entries, exits 0.
- `cli/se doctor` against a configured repo returns 0 if all green, surfaces specific warnings otherwise.

**After Phase C:**
- In a target repo, run `claude` and invoke `/ship-bugfix <bug-id>`. Observe last-line signal matches the contract.
- Run `/ship-qa <id>` and observe `QA_COMPLETE` with a report path.

**After Phase D:**
- `cli/se start grava --dry-run` prints the tmux commands.
- `cli/se start grava` creates `tmux:stella-grava`, the orchestrator loops, one ready bug ships end-to-end.
- `cli/se stop grava` drains and tears down cleanly.

**After Phase E:**
- `cli/se status` enumerates running orchestrators.
- `cli/se teams grava` lists in-flight issues.
- `cli/se pause grava` halts new dispatches; existing in-flight continues.

**After Phase F:**
- A knowledge source path produces draft markdown specs.
- Operator promotes → `upload_project_pages.py` writes to Plane → `/generate` triggers `task-generator` Phase A.

**After Phase G:**
- Kill `cli/se` mid-run; restart; observe correct re-entry.
- `logs/cost.jsonl` accumulates per-repo token usage.
- Integration test (3 fake repos) → all ship one PR; tear down clean.

---

## 7. Sequencing and parallelism

```
A1 ─> A2 ──┬──> A3 ──> A4 ────────────────────────────┐
           │                                          │
           └──> [ship-bug plan Phases A–D run in     │
                 parallel with Phase B–F here]       │
                                                      │
B1 ─> B2 ─> B3 ─> B4 ─┬──> D1 ─> D2 ─> D3 ──> E1–E5 ──┤
                      │                               │
                      └──> C1 ─> C2 ─> C3 (parallel) ─┘
                                                       │
                                          F1–F4 (independent of B–E)
                                                       │
                                          G1–G5 (after all above stable)
```

**Hard sequencing rules:**

- **A1 blocks everything.** No further work until `orchestrator/` is committed.
- **B1 blocks B2–B4** (skeleton must exist before subcommands).
- **C1 + C2 block D2** (`se start` invokes the skills via the orchestrator).
- **D1 blocks D2** (agent file must exist before tmux launches it).
- **F is independent of B–E.** Generator can be authored without fleet runtime; it lands specs into Plane via the existing `upload_project_pages.py`.
- **G is last.** Hardening assumes the components exist.

**Pacing:** allow one week of real-workload exercise between phase bands (A → BCD → E → F → G). Bands inside a row may parallelize across two operators.

---

## 8. Out of scope for this plan

- Detailed `/ship-bugfix` implementation — owned by [`docs/ship-bug/plan.md`](../ship-bug/plan.md).
- Grava → Plane state sync details — owned by [`docs/grava-plane-status-sync-plan.md`](../grava-plane-status-sync-plan.md).
- Self-host Plane operational plan — owned by [`docs/self-host/self-host-plane-plan.md`](../self-host/self-host-plane-plan.md).
- Cross-repo dependency resolution between grava issues — strategy §6 non-goal.
- Bidirectional Plane ↔ grava sync — strategy §9 D8.
- A Stellar web UI — strategy §6 non-goal.
