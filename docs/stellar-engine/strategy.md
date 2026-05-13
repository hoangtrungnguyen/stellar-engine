# Stellar Engine — Strategy

**Status:** Draft · **Last updated:** 2026-05-13

> Reality-grounded rewrite. The earlier "fleet of tmux orchestrators driving `/ship` loops across N repos" framing in `~/Desktop/files/stellar-engine-{strategy,plan}.md` describes a future state. This document describes what stellar-engine **is today** (two sub-agents + sync utilities) and how it grows toward that fleet vision.

---

## 1. Problem

A target repository that uses grava + Plane has three friction points around the `/ship` developer pipeline:

- **Upstream gap.** Specs are hand-written into Plane pages; the path from a spec page to actionable grava issues is manual and error-prone.
- **Dispatch gap.** Operators triage and route grava issues to the right team (epic expansion, bug fix, QA, code task) by hand. Each routing decision is a context switch.
- **Coordination gap.** Once a PR is open, operators track its lifecycle (merged / closed / new comments) and re-enter the pipeline manually.

A fleet-level fourth gap — supervising **many** target repos at once — exists but is not yet pressing while we operate one target repo at a time.

---

## 2. Thesis

Stellar Engine is a **sibling toolkit** that lives next to its target repos and ships three classes of artifact:

1. **Sub-agents** that operate on a target repo's grava DB and Plane workspace via `--target-repo` flags. Today: `task-generator` (Plane → Plane + Grava mirror) and `orchestrator` (in-repo issue router with four teams).
2. **Stateless CLI scripts** that own state transitions through grava wisps. Each agent's "actions" are scripts under `agents/<name>/cli/`. Wisps are the source of truth; scripts are crash-recoverable.
3. **Plane sync utilities** for pushing markdown docs into Plane (project pages, workspace wikis).

The fleet-level runtime (`se` CLI, per-repo tmux orchestrators, `repos.yaml`) is a **future shell** that wraps these agents — not a replacement for them. The current orchestrator agent runs **inside a single Claude session** and routes issues for one target repo at a time; multi-repo coordination is a later wrap.

```
┌─────────────────────────────────────────────────────────────────────┐
│  Operator  →  Claude Code session  →  /generate | /deploy | /qa     │
└────────────────────────────┬────────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     stellar-engine sub-agents                       │
│   ┌──────────────────┐         ┌──────────────────────────────────┐ │
│   │ task-generator   │         │ orchestrator (route + dispatch)  │ │
│   │ Plane page →     │         │   ├── epic         → task-gen    │ │
│   │ Plane items +    │         │   ├── bug          → fix-bug     │ │
│   │ Grava issues     │         │   ├── task/story   → /ship       │ │
│   └──────────────────┘         │   └── qa-ready     → qa pipeline │ │
│                                └──────────────────────────────────┘ │
└────────────────────────────┬────────────────────────────────────────┘
                             ▼
         ┌────────────────────────────────────────────────┐
         │  Target repo: grava DB + .claude/ + .worktree/ │
         └────────────────────────────────────────────────┘
                             ▲
         ┌───────────────────┴────────────────────────────┐
         │  Plane.so workspace (source of spec pages)     │
         └────────────────────────────────────────────────┘
```

---

## 3. Components

### 3.1 Built (today)

| Component | Path | Status | Purpose |
|:---|:---|:---|:---|
| `task-generator` agent | `agents/task-generator/` | Phase 6 shipping | Convert Plane spec page → planned epic/story/task hierarchy → write to Plane (with `blocking` relations) → mirror to Grava. Three-phase: preview / Plane / Grava. Operator approval per turn for each non-`--dry-run` phase. |
| `orchestrator` agent | `agents/orchestrator/` | Untracked but working | Route grava issues to 4 teams (`task-generator`, `epic-task`, `fix-bug`, `qa`). Entry: `/deploy`, `/generate`, `/qa`. Wisps persist state across re-entry. |
| `fix-bug` pipeline | `agents/orchestrator/cli/fix_bug_{claim,verify,pr}.py` + AGENT.md §Fix-Bug | Shipping (Go only) | Claim → Claude-in-worktree (reproduce/RC/fix/regression) → verify → PR. Retry cap 2. Slot freed at PR. See [`docs/ship-bug/strategy.md`](../ship-bug/strategy.md). |
| `qa` pipeline | `agents/orchestrator/cli/qa_{load,report}.py` + checklist templates | Shipping | Load checklist (cli/api/web/mobile/default) → Claude walks items → write results JSON → generate report → post to grava + label `qa-passed`/`qa-failed`. |
| PR merge watcher | `agents/orchestrator/scripts/pr_merge_watcher.sh` | Shipping | Cron-style polling of `pr-created` labeled issues. Handles MERGED (close + signal), CLOSED (label `pr-rejected`, re-entry hint), OPEN (stale cap, new comment detection). |
| Project registry | `repo-map.yaml` + `systems/<Name>/system.yaml` | Shipping | Plane project UUID → repo metadata (name, git_url, workspace_prefix). Per-system override wins on conflict. |
| Plane sync utilities | `upload_project_pages.py`, `upload_wiki_page.py` | Shipping | Push local markdown → Plane project pages / workspace wiki. State persisted in `.plane-pages.json` / `.plane-workspace-pages.json`. |
| Setup script | `setup.sh` | Shipping | Install `@aaronshaf/plane` CLI via bun + Python deps; save credentials to `~/.config/plane/config.json`. |
| MCP wiring | `mcp-setup.md` | Doc | Instructions for connecting Plane MCP server to Claude Code session. |
| System spec template | `systems/SportBuddies/` | Reference | Sample showing the expected layout: `business/`, `design/`, `customer_app/`, `owner_dashboard/`, `backend_core/`, `a2a/`, `web_intro/`. |

### 3.2 Planned (roadmap)

| Component | Status | Purpose | Sub-doc |
|:---|:---|:---|:---|
| `/ship-bugfix` exposed skill | Plan exists | Expose orchestrator's internal fix-bug as a callable skill so Stellar fleet-runtime can dispatch by skill name. | [`docs/ship-bug/plan.md`](../ship-bug/plan.md) |
| Pluggable verify backends | Plan exists | Replace Go-only `fix_bug_verify.py` with per-language backends (Python/Node/Rust/…). | [`docs/ship-bug/plan.md`](../ship-bug/plan.md) §B |
| Grava → Plane state sync | Plan exists | One-way grava issue state → Plane work item state on each coding-team transition. Per-agent hooks in v0. | [`docs/grava-plane-status-sync-plan.md`](../grava-plane-status-sync-plan.md) |
| Self-host Plane | Plan exists | Run Plane locally so workspace state is owned. | [`docs/self-host/self-host-plane-plan.md`](../self-host/self-host-plane-plan.md) |
| `se` CLI | Not started | Operator control plane for fleet runtime (init/repos/doctor/start/stop/status/teams/attach/logs/pause/resume/nudge). | (this doc + companion plan.md) |
| `stellar-orchestrator` agent | Not started | Per-repo thin wrapper looping `/ship-*` skills (instead of in-Claude `/deploy`). | (this doc + plan.md) |
| `repos.yaml` runtime registry | Not started | Fleet-runtime registry: repo name → path + max_concurrent + poll/idle intervals + team_routing. Distinct from `repo-map.yaml` (which maps Plane project UUID → repo). | (this doc + plan.md) |
| `policies/default.yaml` | Not started | Global fleet policies: concurrency ceiling, ship_timeout, failure_streak auto-pause. | (this doc + plan.md) |
| Generator agent | Not started | Knowledge source (codebase / doc / transcript) → markdown specs that feed `task-generator`. | (this doc + plan.md) |

---

## 4. Principles

1. **Sibling, not replacement.** Stellar Engine sits next to target repos and operates on them via flags. It does not embed itself inside them. Each target repo owns its own `.claude/`, grava DB, and `/ship` skill.
2. **Wisps are state; scripts are stateless.** All pipeline state lives in grava wisps. CLI scripts can be re-run safely; they read wisps to decide whether work is already done.
3. **Reuse, don't fork.** `fix_bug_pr.py` mirrors `/ship`'s pr-creator signal contract. The orchestrator's `epic-task` team delegates to the target repo's existing `/ship` skill. We do not rebuild `/ship`.
4. **Files before issues.** Spec markdown is reviewable on disk before it becomes Plane work items or grava issues. The Generator (future) outputs files; the operator approves before `task-generator` writes.
5. **Approval per turn for destructive ops.** Every non-`--dry-run` invocation of `task-generator` requires explicit operator approval in the current turn. Likewise for the orchestrator's `task-generator` team and PR creation paths.
6. **Bounded retry; halt on streak.** Self-verify retries at 2; failure-streak ≥ N (future) auto-pauses. Never auto-bypass `needs-human`.
7. **Slot freed at PR, not at merge.** Fleet throughput must not block on async human review.
8. **Operator in the loop on edge cases.** Cannot-reproduce, duplicate Plane pages, dep cycles, missing Plane types — all halt loudly with a specific exit code and message. No silent guesses.

---

## 5. Success Criteria

| Dimension | Goal |
|:---|:---|
| Spec → backlog latency | One Plane page → epic + stories + tasks in grava ≤10 min (excluding operator review of preview) |
| Bug pipeline completion | ≥90% of claimed bugs reach `pr_created` without operator intervention (Go target repo) |
| QA throughput | One QA run per checklist class with ≤2 operator interactions |
| Routing accuracy | ≥95% of `/deploy <id>` invocations dispatched to the correct team without `--team` override |
| Re-entry correctness | 100% of `pipeline_phase=pr_created` re-entries handle `pr_new_comments` or `pr-rejected` correctly |
| Crash recovery | Killing any CLI mid-run and re-invoking returns to the right phase 100% of the time (idempotency invariant) |

Operator experience target: open a Plane spec page, run `/generate`, approve previews, watch the orchestrator move issues from claim → PR with grava as the audit trail. Re-entry on PR review with one `/deploy <id>` command.

---

## 6. Non-Goals

- **Per-issue intelligence.** Coding lives in `/ship` (epic-task team) and in the fix-bug pipeline's Claude-in-worktree phase. Stellar Engine does not write business logic.
- **PR merge tracking semantics.** `pr_merge_watcher.sh` handles state transitions, but the human review process is not Stellar's concern.
- **Cross-repo dependency resolution.** Grava issues can reference other repos in comments but Stellar does not resolve or block on them.
- **Direct grava writes from the Generator.** Generator (future) writes markdown only; the path to grava goes through `task-generator` → `/plan` and preserves the approval gates.
- **A web UI.** Plane.so is the stakeholder surface; the CLI + Claude Code is the operator surface.
- **A general task runner.** Stellar Engine is scoped to the grava/Plane/`/ship` stack. Use Make or just for general automation.

---

## 7. Phased Rollout

| Phase | Component | Outcome | Status |
|:---|:---|:---|:---|
| 1 | `task-generator` Phases 1–6 | Plane → Plane + Grava mirror with deps | ✅ shipped |
| 2 | `orchestrator/` agents + CLI scripts | In-Claude routing for 4 teams | ✅ shipped (untracked on `main`) |
| 3 | Commit + test `orchestrator/`; pluggable verify | Stable foundation for fleet wrap | ⬜ in progress (see plan.md) |
| 4 | `/ship-bugfix`, `/ship-qa` standalone skills | Callable team skills with stable signal contract | ⬜ planned ([ship-bug plan](../ship-bug/plan.md)) |
| 5 | Grava → Plane state sync (v0) | One-way state mirror via per-agent hooks | ⬜ planned ([sync plan](../grava-plane-status-sync-plan.md)) |
| 6 | `se` CLI Phase 1 (read-only) | `se init`, `se repos`, `se doctor` | ⬜ planned |
| 7 | `stellar-orchestrator` agent + tmux lifecycle | Fleet runtime hosting per-repo loops | ⬜ planned |
| 8 | `se` Phase 2–3 (lifecycle + visibility) | `start`/`stop`/`status`/`teams`/`logs`/`pause`/`resume`/`nudge` | ⬜ planned |
| 9 | `team_routing` policy layer | Per-repo concurrency, type-routing, failure-streak auto-pause | ⬜ planned |
| 10 | Generator agent | Knowledge source → spec markdown | ⬜ planned |
| 11 | Hardening | Crash recovery across all components, cost tracking, integration tests | ⬜ planned |

**Rule:** do not start Phase N+1 until Phase N has been exercised on a real workload for a week. Generator and fleet runtime wait until in-Claude orchestrator + sub-pipelines are trusted.

---

## 8. Risks & Mitigations

| Risk | Mitigation |
|:---|:---|
| `orchestrator/` directory loss (untracked on main) | Phase 3 commits it. Treat this as a P0 plan item |
| Go-only verify limits target-repo scope | Pluggable backends in plan.md gap 3 |
| Two registries (`repo-map.yaml`, future `repos.yaml`) drift | Distinct keys (UUID vs name) + cross-link comments + `se doctor` cross-validation |
| task-generator + future Observer both write Plane | Lock `state` field ownership: only the state-sync owns `state` on update paths; `task-generator` never sets `state` |
| Approval-per-turn fatigue | Acceptable cost: every Plane / Grava destructive write is consequential. Add `--yes-confirm-token` only if operator demands |
| Wisp state corruption on partial scripts | Scripts checkpoint to `.grava/<name>-<id>-*.json` and emit JSON exit envelopes |
| PR watcher cron drift / not running | Singleton PID guard + heartbeat check (TODO); document `*/5 * * * *` install in setup |
| Multiple Claude sessions race on `grava claim` | grava enforces single-claimant at DB; `fix_bug_claim.py` exits 2 cleanly |
| Plane workspace state drifts from grava | One-way sync (grava → Plane) keeps grava authoritative; Plane edits are advisory |
| Self-host Plane outages back up sync | Local jsonl queue + replay (future when grava→Plane sync upgrades from per-agent hook to watermark observer) |

---

## 9. Decision Log

**D1: Sub-agents over fleet daemons (today).** The current scale (≤2 target repos) does not justify per-repo tmux daemons. The in-Claude orchestrator + `--target-repo` flag is simpler, debuggable, and proven. Fleet daemon shape is reserved for Phases 7–8 when N ≥ 5.

**D2: One orchestrator per Claude session, not per target repo.** Routing across repos happens by re-running `/deploy --target-repo <path>`. Per-repo state lives in that repo's grava DB; no shared in-memory state needed.

**D3: Wisps as the state machine.** Database-backed state (vs. files in `.grava/` or in-process memory) means any agent — including a re-entered Claude session — can resume cleanly. Scripts read phase wisps before doing work.

**D4: Two registries, distinct purposes.** `repo-map.yaml` is keyed by Plane project UUID for the `task-generator` lookup. The future `repos.yaml` (fleet runtime) will be keyed by repo name with runtime config. They do not merge — different consumers, different lookup keys.

**D5: Operator approval per turn.** "Yes earlier today" does not count. Each destructive Plane / Grava write requires fresh acknowledgement in the current Claude turn.

**D6: `qa-ready` label overrides issue type.** Routing checks label first, type second. Lets an operator route a bug into QA verification without changing the issue type.

**D7: Slot freed at PR creation.** Async human review must not throttle backlog throughput. The watcher re-enters on PR closed / new comments via wisps.

**D8: Plane sync is one-way (grava → Plane).** Bidirectional sync is a known foot-gun. Plane edits are advisory; grava remains authoritative.

**D9: Defer fleet runtime until in-Claude orchestrator hits scale limits.** Building `se` CLI and `stellar-orchestrator` before the in-Claude version proves itself adds complexity without solving an observed bottleneck.

---

## 10. Open Questions

1. **Skill exposure model.** Should `/ship-bugfix` and `/ship-qa` live in each target repo's `.claude/skills/` (per Stellar plan), or remain as orchestrator-internal entry paths (current `/deploy`)? Cost vs benefit?
2. **Multi-repo bugs.** A symptom in repo A caused by repo B — single `/deploy` invocation that spans both, or split per repo?
3. **Generator input scope.** Codebases only, or also URLs, transcripts, calls? What is the smallest useful first version?
4. **Cost ceiling per repo.** Where does the budget come from when fleet runtime exists? Per-repo wisp? Global policy?
5. **Server-hosted fleet or laptop-only?** Affects pause/resume design, persistence, and identity.
6. **Plane project mapping.** One repo per Plane project, or configurable many-to-one / one-to-many?
7. **Re-entry trigger on PR comments.** Today: operator runs `/deploy <id>`. Future fleet: watcher writes wisp + stellar-orchestrator polls + auto-enters. Where should the trigger boundary land?
8. **Identity per agent.** Single `stellar-engine` actor or per-team actor (`fix-bug-orchestrator`, `qa-reviewer`, …)? Useful for grava audit logs.

---

## 11. Anti-Strategy

Stellar Engine is **not**:

- A Kubernetes operator (CLI + filesystem flags suffice; tmux is the only daemon).
- A CI/CD system (runs upstream of CI; merge gates remain on GitHub).
- A project management tool (Plane.so is).
- A multi-tenant service (one operator, one machine, one set of credentials).
- A knowledge management system (Generator reads sources; it does not curate).
- A general code mode (refactors and features go through `/ship`; bugs go through `/ship-bugfix`).
- A grava replacement (we operate on grava; we do not extend its data model except via wisps).
- A Plane SDK (we use Plane's REST API for narrowly defined writes).

Boundary: **upstream of `/ship`, around it, and downstream up to PR creation.** Past PR creation, GitHub + `pr_merge_watcher.sh` handle the long tail.
