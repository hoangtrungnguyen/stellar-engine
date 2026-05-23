# Generator v2 — absorb task-generator, add Plane + grava writes, add tech-plan

**Status:** Draft (planning) · **Branch:** `feat/generator-absorbs-taskgen` · **Worktree:** `.claude/worktrees/feat-generator-absorbs-taskgen`

This plan reshapes the generator agent from a read-only markdown renderer into the single agent that owns the entire `source → Plane → grava` pipeline. The `task-generator` agent is **removed**. The generator becomes **orchestrator-driven only** — no direct operator entry for Plane / grava writes; everything goes through `se o generate …`.

---

## 1. Goals (user stories, verbatim)

### Connect to Plane API
- As a generator agent, I can search Plane APIs.
- As a generator agent, I can download pages from Plane projects.
- As a generator agent, I can create / delete / update / read Plane issues from Plane.so.

### Enable grava actions
- As a generator agent, I can generate mirror issues from a Plane project to a repository folder.
- As a generator agent, I can use grava to read / write / update / delete grava issues in a repository folder.

### Tech document modification
- As a generator agent, I can modify a tech-plan for a repository folder in a format that links to a Plane issue and a grava issue.

### Other
- The generator must **never** accept PDF input. The deferred PDF frontend is cancelled.

---

## 2. Out of scope (this branch)

- **AC-on-work-item fold** — separate branch (`feat/ac-in-description`).
- Phase D LLM outline — still deferred, still manual via Claude Code session.
- PDF / URL / transcript / codebase frontends — `extract.py` now hard-rejects non-`.md` with a permanent (not deferred) error.
- `grava_plane_sync.py` algorithmic changes — code migrates path, behaviour unchanged.

---

## 3. Architecture: before vs after

### Before (current main)

```
                                            ┌── upload_project_pages.py
                                            │
operator → se generate <src> ──► drafts/*.md (manual promote) ──► systems/<N>/business/*.md ──┤
                                                                                              │
                                                                                              ▼
                                                                                          Plane page
                                                                                              │
operator → se taskgen <proj> <page> ──► task-generator: parser → planner → plane_writer ──► Plane work items
                                                                       └────► grava_writer ──► grava issues
                                                                       
grava signal hooks ──► agents/task-generator/cli/grava_plane_sync.py ──► Plane state PATCH
```

Two agents (`generator`, `task-generator`), one v0 sync layer, manual handoffs.

### After (this plan)

```
orchestrator dispatch (se o generate …)
        │
        ▼
generator agent
  ├── extract     source.md → extract.json                    (existing)
  ├── outline     extract.json → outline.json  (manual)        (existing)
  ├── render      outline.json → drafts/*.md                  (existing)
  ├── publish     drafts/*.md → Plane page                    (new — absorbs upload_project_pages.py for project-scoped use)
  ├── taskify     Plane page → Plane work items + relations   (new — absorbs task-generator/{parser, planner, plane_writer})
  ├── mirror      Plane work items → grava issues             (new — absorbs task-generator/grava_writer)
  └── techplan    epic → systems/<N>/business/tech-plan-<slug>.md with Plane + grava IDs in frontmatter (new)

grava signal hooks ──► agents/generator/cli/grava_plane_sync.py ──► Plane state PATCH    (migrated, unchanged)
```

One agent. Orchestrator dispatches each phase. Operator approval still required per phase.

---

## 4. Inventory

### Migrated from `agents/task-generator/` → `agents/generator/`

| Source | Destination | Notes |
|:---|:---|:---|
| `task-generator/plane_client.py` | `generator/plane_client.py` | Auth + GET/POST/PATCH/DELETE primitives. Reused by every Plane phase. |
| `task-generator/repo_map.py` | `generator/repo_map.py` | UUID → repo resolver. Unchanged. |
| `task-generator/parser.py` | `generator/plane_parser.py` *(renamed)* | Parses Plane page body → EpicNode IR. Distinct from `generator/parser/markdown.py` (source-doc parser). |
| `task-generator/planner.py` | `generator/planner.py` | EpicNode → CreateWorkItem op list. |
| `task-generator/plane_writer.py` | `generator/plane_writer.py` | Op-list → Plane API calls. |
| `task-generator/grava_writer.py` | `generator/grava_writer.py` | Mirror Plane hierarchy → grava issues. |
| `task-generator/dependency_analyzer.py` | `generator/dependency_analyzer.py` | Mermaid → blocking relations. |
| `task-generator/reconcile.py` | `generator/reconcile.py` | Idempotent re-run logic. |
| `task-generator/cli/grava_plane_sync.py` | `generator/cli/grava_plane_sync.py` | **Critical** — invoked by grava hooks. Path change requires updating hook configs + `STELLAR_ENGINE_HOME` docs. |
| `task-generator/cli/preflight.py` | `generator/cli/preflight.py` | Plane + grava sanity checks. |
| `task-generator/ir.py` | merge into `generator/ir.py` | One unified IR file. Existing generator outline classes stay; task-generator IR classes (TaskNode, StoryNode, EpicNode, RunPlan, RunReport, RunState, GravaState, etc.) added. |
| `task-generator/tests/*` | `generator/tests/*` | All tests move; imports rewritten. |

### Deleted (no replacement)

| Path | Reason |
|:---|:---|
| `agents/task-generator/` (whole tree, post-migration) | Agent removed. |
| `cli/se` `cmd_taskgen` + `taskgen` subparser | Replaced by `se o generate taskify <project> <page>` (orchestrator-mediated). |
| `agents/orchestrator/cli/task_gen_expand.py` | Replaced by `generator_taskify.py` (see §5). |
| `agents/generator/cli/outline.py` (the `--llm` path) | Stays skeleton-only; Phase D still deferred. No change. |

### New (this branch)

| Path | Purpose |
|:---|:---|
| `agents/generator/cli/publish.py` | Upload `drafts/*.md` to a Plane project page (per-project, not workspace wiki). |
| `agents/generator/cli/taskify.py` | Plane page → Plane work items + blocking relations. Wraps parser/planner/plane_writer. |
| `agents/generator/cli/mirror.py` | After taskify: Plane → grava mirror. Wraps grava_writer. |
| `agents/generator/cli/techplan.py` | Per-epic tech-plan markdown emitter. |
| `agents/generator/plane_search.py` | Plane search wrapper (projects, pages, issues by query). Powers “search for Plane APIs” story. |
| `agents/orchestrator/cli/generator_publish.py` | Bridge: `se o generate publish` → `generator/cli/publish.py`. |
| `agents/orchestrator/cli/generator_taskify.py` | Bridge: `se o generate taskify` → `generator/cli/taskify.py`. Replaces `task_gen_expand.py`. |
| `agents/orchestrator/cli/generator_mirror.py` | Bridge: `se o generate mirror` → `generator/cli/mirror.py`. |
| `agents/orchestrator/cli/generator_techplan.py` | Bridge: `se o generate techplan` → `generator/cli/techplan.py`. |
| `agents/generator/tests/test_publish_cli.py`, `test_taskify_cli.py`, `test_mirror_cli.py`, `test_techplan.py`, `test_plane_search.py` | One test file per new CLI. |
| `docs/generator/v2-architecture.md` | Operator-facing architecture doc (this plan distilled). |
| `docs/generator/tech-plan-format.md` | Tech-plan markdown spec + frontmatter schema (see §7). |

### Edited

| Path | Change |
|:---|:---|
| `cli/se` | Remove `cmd_taskgen` + `taskgen` subparser. Replace `cmd_plane_sync` invocation path. Add `se o generate {extract,outline,render,publish,taskify,mirror,techplan}` subcommands. |
| `cli/se` `cmd_doctor` | Drop task-generator package check, add generator Plane + grava write checks. |
| `agents/generator/AGENT.md` | Rewrite. Remove “NEVER call Plane API / grava” hard limits. Add orchestrator-only entry rule. Document new phases + tech-plan. |
| `agents/orchestrator/AGENT.md` | Replace “task-generator team” → “generator team”. Update routing table. Update example bash. |
| `agents/orchestrator/cli/route.py` | `epic` type → `team="generator"` (was `task-generator`). |
| `agents/orchestrator/cli/pick_ready.py` | Same team rename. |
| `agents/orchestrator/cli/daemon.py` | Team list update. |
| `docs/stellar-engine/strategy.md`, `docs/stellar-engine/plan.md`, `CLAUDE.md` | Strike task-generator references. Add generator v2 section. |
| `docs/grava-plane-sync-setup.md` | New path: `agents/generator/cli/grava_plane_sync.py`. Hook examples updated. |
| `setup.sh` | Drop task-generator install lines, ensure generator’s new deps present. |
| `agents/generator/cli/extract.py` | PDF deferral note → hard `.md` enforcement (already enforced, just removes “(deferred)” language). |
| `docs/generator/plan.md` | Add Phase H section pointing at this plan. |
| `repo-map.yaml` | Schema unchanged. Comment block updated (consumer is now generator). |
| Hook configs in target repos | Operator-facing — `grava_plane_sync.py` path changed; doc update is mandatory, code change is not. |

---

## 5. Orchestrator-mediated entry surface

All operator entry to Plane / grava writes goes through `se o generate <phase>`. No `se generate <phase>` for write phases.

| Operator command | Bridge script | Underlying generator script | Notes |
|:---|:---|:---|:---|
| `se o generate extract <src>` | `generator_extract.py` (new) | `generator/cli/extract.py` | Read-only. Can also run via `se generate extract` (no bridge needed). |
| `se o generate outline <src>` | n/a | manual | No code path today. Documented. |
| `se o generate render <src>` | `generator_render.py` (new) | `generator/cli/render.py` | Read-only. `se generate render` still works. |
| `se o generate publish <src> --plane-project <code\|uuid>` | `generator_publish.py` | `generator/cli/publish.py` | Writes Plane page(s) from a draft. Requires operator approval this turn. |
| `se o generate taskify <project> <page>` | `generator_taskify.py` | `generator/cli/taskify.py` | Replaces `se taskgen` and `se o expand`. Plane page → work items. Requires approval. |
| `se o generate mirror <project> <page> --target-repo <path>` | `generator_mirror.py` | `generator/cli/mirror.py` | Mirrors a taskified page to grava. Requires approval. |
| `se o generate techplan <epic-id> --target-repo <path>` | `generator_techplan.py` | `generator/cli/techplan.py` | Emits `systems/<N>/business/tech-plan-<epic-slug>.md` with Plane + grava IDs in frontmatter. Idempotent. |

**Read-only phases** (`extract`, `render`) still expose `se generate <phase>` directly for the local-draft workflow. Write phases (`publish`, `taskify`, `mirror`, `techplan`) **only** exist under `se o generate`.

**Approval gates** carry over from task-generator: each write phase requires explicit `--yes` and a preview pass first.

---

## 6. New scopes — Plane API + grava actions

### 6.1 Plane API capability

The migrated `plane_client.py` already covers GET / POST / PATCH / DELETE for issues, pages, projects, labels, relations. New work:

- **Search wrapper** (`generator/plane_search.py`):
  - `search_projects(query: str) -> list[ProjectRef]`
  - `search_pages(project_id: str, query: str) -> list[PageRef]`
  - `search_issues(project_id: str, query: str, *, types: list[str] | None = None) -> list[IssueRef]`
  - Backed by Plane’s `/api/v1/workspaces/<slug>/projects/<id>/issues/?search=…` and the equivalent page search endpoint. Auth + workspace via existing `~/.config/plane/config.json`.
- **Download pages**: already covered by `cli/se download`. Migration target: `cli/se download` continues to work; internal call moves from `task-generator/cli/grava_plane_sync.py`-adjacent helpers to `generator/plane_client.py`. No new CLI surface.
- **Issue CRUD**: already covered by `plane_client.py` + `plane_writer.py`. The orchestrator dispatches via `taskify` / `mirror`; `plane_writer.py` learns one new public method `delete_issue(project_id, issue_id)` (currently absent — task-generator never deletes).

### 6.2 grava actions

- Mirror generation: handled by `mirror.py` (wraps existing `grava_writer.py`).
- CRUD: grava CLI is invoked via `subprocess.run(["grava", ...])` from `grava_writer.py` for create. New helpers:
  - `grava_update(issue_id, *, status=None, labels=None, assignee=None)` — already exists in `grava_plane_sync.py` patch path; promote to `generator/grava_client.py`.
  - `grava_delete(issue_id)` — new wrapper around `grava issue delete <id>` (or whatever the grava CLI exposes — verify before coding).
  - `grava_read(issue_id)` — wraps `grava show <id> --json`.
- The orchestrator surfaces these only indirectly, via `mirror` and `techplan`. Direct CRUD endpoints are not exposed as separate commands in v1 — they’re library calls inside `taskify` / `mirror` / `techplan`.

---

## 7. Tech-plan format

### File location

```
systems/<SystemName>/business/tech-plan-<epic-slug>.md
```

One file **per epic** in the system. Filename slug derived from `epic.title` (kebab-case, lowercased, ascii-only). If a previous tech-plan exists, the generator updates frontmatter in place but never overwrites the body without operator approval.

### Frontmatter schema

```yaml
---
generator_source: <abs path to draft markdown that produced this epic>
generator_run_id: <RID>
plane_project_id: <uuid>
plane_project_code: <e.g. CAPP, STELL>
plane_page_id: <uuid of the spec page the epic was taskified from>
plane_issue_id: <uuid of the Plane work item for this epic>
plane_issue_sequence_id: <int — Plane’s human-readable ID, e.g. 142>
grava_issue_id: <e.g. EPIC-12>
grava_repo_path: <abs path to target repo with .grava>
created_at: <ISO 8601>
updated_at: <ISO 8601>
schema_version: 1
---
```

### Body structure

```markdown
# <Epic title>

> Plane: [<project_code>-<sequence_id>](https://app.plane.so/<workspace>/projects/<project_uuid>/issues/<issue_uuid>) · Grava: `<grava_issue_id>`

## Summary

<epic.summary from outline.json>

## Stories

- **<story title>** — Plane `<project_code>-<seq>` · Grava `<grava_id>`
  - Tasks: `<task_id>`, `<task_id>`, …

## Dependencies

> Depends on: <other epic refs as Plane + grava cross-links>

## Acceptance Criteria

<one bullet per criterion, copied from the upstream draft>

## UI/UX Design

<links, if any>

## Tech notes

<free-form area for engineers — generator leaves this empty on create; never touched on update>
```

The bottom `## Tech notes` section is intentionally generator-empty; engineers edit it manually. Generator updates above-`## Tech notes` content on re-run, preserves the tech-notes block byte-for-byte.

### Authoring guide

Lives at `docs/generator/tech-plan-format.md` (created in this branch). Covers field semantics, link resolution rules, what happens on epic rename, how to query all tech-plans for a system.

---

## 8. Phase plan

### Phase H0 — Inventory + migration scaffolding (this PR’s first commit)

- Land this plan doc at `docs/generator/absorb-taskgen-plan.md`.
- No code moves yet. PR opens for review of the plan before any breaking change.
- **Verify:** repo still builds; all current tests pass (`pytest agents/generator/tests/ agents/task-generator/tests/ agents/orchestrator/tests/`).

### Phase H1 — Migrate task-generator → generator (no behaviour change)

- Copy files per §4 inventory table, with one-line `git mv` per file where possible to preserve history.
- Rewrite imports: `from parser import …` → `from generator.plane_parser import …`, etc.
- Merge `ir.py` files. Resolve name collisions (none expected; generator IR uses `Section`/`Heading`/`Outline`/`Epic` and task-generator uses `EpicNode`/`StoryNode`/`TaskNode` — distinct).
- Update test imports. Run full suite.
- Update `cli/se` paths: `agents/task-generator/cli/run.py` → `agents/generator/cli/taskify.py`. Same internal pattern as `cmd_taskgen`, just relocated.
- Update `agents/orchestrator/cli/task_gen_expand.py` → `generator_taskify.py`. Same algorithm.
- **Verify:** `pytest agents/generator/tests/ agents/orchestrator/tests/`. End-to-end smoke: `se o generate taskify <project> <page> --dry-run` produces the same preview as the old `se taskgen … --dry-run`.

### Phase H2 — Delete `agents/task-generator/`

- After H1 lands and CI is green for a tick: `git rm -r agents/task-generator/`.
- Strip residual references from `CLAUDE.md`, `README.md`, `docs/stellar-engine/{strategy,plan}.md`, `agents/orchestrator/AGENT.md`, `setup.sh`.
- Add stub `agents/task-generator/REMOVED.md` for one release (optional — point readers at generator). Decision in PR.
- **Verify:** `grep -rn "task-generator\|task_gen" .` returns only history / archive matches.

### Phase H3 — New CLI surfaces: publish, mirror, techplan, plane_search

- Build `generator/cli/publish.py` — wraps `upload_project_pages.py` semantics for per-project use. Reuses `plane_client.py`.
- Build `generator/cli/mirror.py` — extracts the grava-write half of the old `taskify` flow into its own phase. Idempotent; safe to re-run.
- Build `generator/cli/techplan.py` — per-epic tech-plan emitter. Reads outline.json + post-taskify state + post-mirror state to fill frontmatter.
- Build `generator/plane_search.py` + tests.
- Wire bridges in `agents/orchestrator/cli/`.
- Wire `se o generate <phase>` subcommands in `cli/se`.
- **Verify:** unit tests for each new module; integration smoke against sandbox.

### Phase H4 — `grava_plane_sync.py` path migration

- Move `agents/task-generator/cli/grava_plane_sync.py` → `agents/generator/cli/grava_plane_sync.py`.
- Update `docs/grava-plane-sync-setup.md` with the new path.
- Symlink or shell-shim during a deprecation window? Decision in PR. **Recommendation:** no shim — break loudly. Operators must update their hooks once.
- **Verify:** in sandbox repo, replace the hook command with the new path; trigger `grava signal` and confirm Plane state still patches.

### Phase H5 — AGENT.md + CLAUDE.md rewrite, doctor checks update

- Rewrite `agents/generator/AGENT.md` per new scope (Plane + grava writes allowed under orchestrator dispatch; PDF hard-banned).
- Rewrite `agents/orchestrator/AGENT.md` team table.
- Update `cli/se doctor` checks: drop task-generator module check, add generator Plane + grava client checks (`plane_client` importable, `grava` CLI on PATH, etc.).
- **Verify:** `se doctor` exits clean on a configured machine.

### Phase H6 — Documentation

- Author `docs/generator/v2-architecture.md` (operator-facing).
- Author `docs/generator/tech-plan-format.md`.
- Update `docs/generator/usage.md` for the new flow (`se o generate …`).
- Update `README.md` quick-start.
- **Verify:** docs render clean on GitHub.

### Phase H7 — Release + comms

- Merge to main behind a clear PR title: `feat(generator): absorb task-generator; orchestrator-only entry for Plane/grava writes`.
- Note in `docs/install.md`: operators must update their `grava_plane_sync` hook command.
- Tag release (semver minor or major — operator decides; this is a breaking CLI change).

---

## 9. Hard limits (updated)

The generator’s `AGENT.md` `Hard limits` section becomes:

- **Direct operator entry forbidden for Plane / grava writes.** All write phases (`publish`, `taskify`, `mirror`, `techplan`) only run under `se o generate …`. The bridge script verifies `os.environ.get("STELLAR_ORCH_DISPATCH") == "1"` (set by the orchestrator dispatcher) or refuses with an explanatory error.
- **NEVER process non-`.md` input.** PDF / URL / transcript / codebase frontends are permanently dropped (was deferred).
- **NEVER auto-promote a draft into `systems/<Name>/business/`** without operator approval this turn.
- **NEVER bypass per-phase approval gates.** Each write phase requires explicit `--yes` and a passing dry-run preview.
- **NEVER commit `drafts/`** (gitignored).
- **NEVER overwrite a `## Tech notes` block** in an existing tech-plan markdown file.

Removed limits (were on the old generator):
- ~~NEVER call Plane API~~
- ~~NEVER call grava~~

---

## 10. Testing strategy

- **Unit**: every migrated module keeps its existing tests under `agents/generator/tests/`. Add new tests for `publish`, `mirror`, `techplan`, `plane_search`.
- **Integration (sandbox)**: an end-to-end test fixture: source markdown → `se o generate extract|render|publish|taskify|mirror|techplan` against `stellar-sandbox`. Documented in `docs/generator/v2-architecture.md`.
- **Regression**: confirm `grava_plane_sync.py` behaviour unchanged via the existing `tests/cli/test_grava_plane_sync.py` (migrate alongside its module).

---

## 11. Risk register

| Risk | Mitigation |
|:---|:---|
| Operators have `grava signal` hooks pointing at the old path | Phase H4 doc update + release notes; refuse silently in a future release if we add a shim. |
| `STELLAR_ENGINE_HOME` resolution breaks because the script moved | Verify on a clean machine before merge; update `docs/grava-plane-sync-setup.md`. |
| Test suite churn from import path changes | Use `git mv` to keep history; rewrite imports in a single mechanical commit. |
| Tech-plan format changes break engineers’ hand-edits | The `## Tech notes` carve-out is the contract; document it as preserved-byte-for-byte; add a regression test. |
| Orchestrator routing change (`epic` → `generator` team) breaks in-flight epics in someone’s grava state | Migration note: any wisp with `team: task-generator` is read as `team: generator` for one release. |

---

## 12. Open questions for the operator

1. **Symlink the old `grava_plane_sync.py` path during transition?** Recommendation: no. Two-line script that errors with the new path is friendlier than a silent symlink. Confirm before H4.
2. **Where does `se taskify` (or `se o generate taskify`) emit its preview file today?** Current task-generator writes to `runs/preview/<RID>/*.preview.md`. Keep that path or move under `drafts/<project>/runs/<RID>/`? Recommendation: keep path; just relocate code.
3. **Per-epic tech-plan vs single-file tech-plan-index?** This plan chose per-epic per your spec. Confirm — if you want a single `tech-plan.md` per system that indexes all epics, the format changes materially.
4. **`schema_version` start value** — `1` chosen. Future migration story: when frontmatter shape changes, bump version + add a migration script. OK to ship at v1?

---

## 13. Out of scope (explicit non-goals)

- Multi-workspace orchestration (one workspace at a time).
- Streaming / real-time Plane updates (still batch-on-dispatch).
- Generator-side LLM calls (Phase D still deferred — outline.json still manual).
- Auto-resolution of diff on re-run (operator decides; current rule preserved).
- Auto-promote drafts (still manual operator copy).
