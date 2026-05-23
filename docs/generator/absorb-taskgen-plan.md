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
| `agents/generator/cli/publish.py` | Upload `drafts/*.md` to a Plane project page (per-project, not workspace wiki). Refuses paths under `systems/<N>/business/` (deny-list, §9). |
| `agents/generator/cli/taskify.py` | Plane page OR `--source-md PATH` → Plane work items + blocking relations. Wraps parser/planner/plane_writer. |
| `agents/generator/cli/mirror.py` | After taskify: Plane → grava mirror. Wraps grava_writer. Supports `--from-taskify-run <RID>` resume. |
| `agents/generator/cli/techplan.py` | Per-epic + per-story emitter. Merges with existing files (preserves engineer-owned blocks byte-for-byte). |
| `agents/generator/cli/full.py` | Chain orchestrator (`publish` → `taskify` → `mirror` → `techplan`). Single consolidated preview. |
| `agents/generator/cli/epic_tech_plan_load.py` | Read existing per-epic tech-plan (frontmatter + tech-notes block) for the merge step. |
| `agents/generator/cli/story_spec_load.py` | Read existing per-story spec (frontmatter + all 5 section blocks). |
| `agents/generator/description_composer.py` | Build Plane work item `description_html` from the four sections (Requirements / AC / Tech Plan / UI-UX). Used by `plane_writer` on every create. Rejects QA inputs. |
| `agents/generator/plane_search.py` | Plane search wrapper (projects, pages, issues by query). Powers "search for Plane APIs" story. |
| `agents/generator/state.py` | Cross-phase RunState dataclass + load/save helpers. Replaces task-generator's per-phase state files with one unified shape. |
| `agents/orchestrator/cli/generator_publish.py` | Bridge: `se o generate publish` → `generator/cli/publish.py`. Sets `STELLAR_ORCH_DISPATCH=1` env var. |
| `agents/orchestrator/cli/generator_taskify.py` | Bridge: `se o generate taskify` → `generator/cli/taskify.py`. Replaces `task_gen_expand.py`. |
| `agents/orchestrator/cli/generator_mirror.py` | Bridge: `se o generate mirror` → `generator/cli/mirror.py`. |
| `agents/orchestrator/cli/generator_techplan.py` | Bridge: `se o generate techplan` → `generator/cli/techplan.py`. |
| `agents/orchestrator/cli/generator_full.py` | Bridge: `se o generate full` → `generator/cli/full.py`. |
| `agents/generator/tests/test_publish_cli.py`, `test_taskify_cli.py`, `test_mirror_cli.py`, `test_techplan.py`, `test_full_chain.py`, `test_plane_search.py`, `test_description_composer.py`, `test_story_spec_load.py`, `test_epic_tech_plan_load.py`, `test_state_cross_phase.py` | One test file per new module. |
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

### 5.1 CLI surface

| Operator command | Bridge script | Underlying generator script | Read/write | Notes |
|:---|:---|:---|:---:|:---|
| `se generate extract <src>` | n/a (direct) | `generator/cli/extract.py` | R | Source-md → `extract.json`. No Plane / grava touch. |
| `se generate render <src>` | n/a (direct) | `generator/cli/render.py` | R | Manual `outline.json` → `drafts/*.md`. |
| `se o generate publish <src> --plane-project <code\|uuid> [--page <uuid>] [--dry-run] [--yes]` | `generator_publish.py` | `generator/cli/publish.py` | W | Uploads a draft to a Plane project page (creates new page or replaces an existing one identified by `--page`). Refuses any path under `systems/<N>/business/` (deny-list, §9). |
| `se o generate taskify <project> {<page>\|--source-md PATH} [--dry-run] [--yes] [--rewrite-plane-descriptions]` | `generator_taskify.py` | `generator/cli/taskify.py` | W | Replaces `se taskgen` and `se o expand`. Two source modes: `<page>` (Plane page UUID) or `--source-md PATH` (local md). Emits epics via `/epics/`, stories+tasks via `/work-items/`. Plane work item bodies composed via `description_composer.py` per §7.4. `--rewrite-plane-descriptions` opt-in: also patch existing items' bodies (default: leave engineer-edited descriptions alone). |
| `se o generate mirror <project> {<page>\|--from-taskify-run <RID>} --target-repo <path> [--dry-run] [--yes]` | `generator_mirror.py` | `generator/cli/mirror.py` | W | Plane work items → grava issues. `--from-taskify-run` reuses an existing `runs/work/<RID>/` state so the operator can re-attempt grava after a taskify-success-mirror-fail split. |
| `se o generate techplan {<project> <page>\|--from-taskify-run <RID>} --target-repo <path> [--dry-run] [--yes]` | `generator_techplan.py` | `generator/cli/techplan.py` | W | Emits per-epic + per-story md under `systems/<N>/business/`. Idempotent (preserves engineer carve-outs). Reads `runs/work/<RID>/` state for Plane + grava IDs. |
| `se o generate full <src or page> [--project <code>] [--target-repo <path>] [--dry-run] [--yes]` | `generator_full.py` | `generator/cli/full.py` | W | Chain orchestrator: `publish` (if local md) → `taskify` → `mirror` → `techplan`. Single `--yes` covers the chain; individual phase approval still surfaces in interactive mode. |

**Read-only phases** (`extract`, `render`) still expose `se generate <phase>` directly for the local-draft workflow. Write phases (`publish`, `taskify`, `mirror`, `techplan`, `full`) **only** exist under `se o generate`.

### 5.2 Common flags (apply to every write phase)

| Flag | Default | Behaviour |
|:---|:---|:---|
| `--dry-run` | false | Run preview + state writes; no Plane / grava calls. Exits 0 on success. |
| `--yes` | false | Skip interactive confirmation prompt. Combine with `--dry-run` for unattended preview. |
| `--run-id <id>` | UTC timestamp | Override the generated RID. Used to resume a partial run. |
| `--on-failure {prompt,rollback,abort}` | `prompt` | What to do when a Plane/grava op fails mid-execute. |
| `--json-report <path>` | `<repo>/runs/reports/<RID>.json` | Override report path. |
| `--plane-profile <name>` / `--plane-config <path>` | (env) | Multi-workspace credential selection (existing). |
| `--no-clone` | false | Refuse to auto-clone target repo if missing. |

### 5.3 Exit code matrix

Unified across write phases (current task-generator codes preserved):

| Code | Meaning |
|:---:|:---|
| 0 | Success (including dry-run with non-empty preview). |
| 1 | Bad input — missing file, bad UUID, credentials missing. |
| 2 | Repo unresolved (no entry in `repo-map.yaml` AND no `--target-repo`) OR clone failed. |
| 3 | Preflight failure (duplicate Plane page, missing required types). |
| 4 | Cannot write — Plane work-item type(s) missing (story / task), refuses to continue. |
| 5 | Plane / grava write failed mid-execute (state checkpointed, report written). |
| 6 | Same as 5 but rollback succeeded. |
| 7 | Dependency analyser failure (cycle without `--allow-dep-cycles`, or unresolved refs under `--strict-deps`). |
| 8 | Hard-limit violation: phase invoked outside orchestrator dispatch (write phase only). |
| 9 | Hard-limit violation: `publish.py` deny-listed path (`systems/<N>/business/`). |

### 5.4 Orchestrator routing (grava issue → generator phase)

The orchestrator dispatches generator phases based on the type/state of a claimed grava issue.

```
grava issue                          → generator phase
─────────────────────────────────────────────────────────
type=epic, state=backlog             → se o generate taskify
type=epic, state=in-progress         → se o generate techplan   (refresh local md
                                                                 from latest Plane state)
type=epic, label=plane-out-of-sync   → se o generate mirror     (re-mirror to grava)
type=story, no plane_id wisp         → (refuse — story needs an
                                          epic taskify run first)
type=story, has plane_id wisp        → no generator action; route to epic-task team
```

Routing table updates required (Phase H5):

- `agents/orchestrator/cli/route.py`: `type == "epic"` → `team="generator"` (was `task-generator`).
- `agents/orchestrator/cli/pick_ready.py`: same rename.
- `agents/orchestrator/cli/daemon.py`: team list update.

The orchestrator agent surfaces the dispatched phase + preview to the operator before any write. Per-phase approval lives in the orchestrator dispatcher (it sets `STELLAR_ORCH_DISPATCH=1` for the bridge script; the bridge gates on this env var per §9 hard limits).

### 5.5 Cross-phase chaining (`se o generate full`)

The `full` command runs the four write phases as a single transaction-ish chain. Failure semantics:

```
┌───────────┐  ok  ┌────────────┐  ok  ┌─────────────┐  ok  ┌──────────────┐
│  publish  │ ───→ │  taskify   │ ───→ │   mirror    │ ───→ │  techplan    │
└─────┬─────┘      └─────┬──────┘      └─────┬───────┘      └──────┬───────┘
      │ fail              │ fail              │ fail               │ fail
      ▼                   ▼                   ▼                    ▼
  rollback on        rollback on         rollback on          (no rollback —
  publish only       --on-failure        --on-failure          local files
                     == rollback         == rollback           are idempotent;
                                                               operator can
                                                               re-run techplan
                                                               alone)
```

**Resume**: after a failure, the operator can re-invoke any single phase with `--run-id <prior RID>` to resume from the next un-completed op. The state file in `runs/work/<RID>/state.json` tracks per-phase progress.

**`publish` is conditional**: only runs when the input is a local `<src>` markdown file. If the operator passes a Plane `<page>` directly, `full` skips `publish` and starts at `taskify`.

**Single approval per chain**: `--yes` on `se o generate full ...` covers all four phases. The chain prints a single consolidated preview before executing.

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

The system grows **two** kinds of tech-plan documents that coexist. Neither replaces the other; they answer different questions.

### 7.1 System-level tech-plan (unchanged from current main)

```
systems/<SystemName>/tech-plan.md      ← ONE per system
```

| Property | Value |
|---|---|
| Schema | **Free-form markdown prose.** No frontmatter required. No fixed structure. |
| Audience | Session-level context for the generator agent. Loaded once at the start of a run; the agent applies judgment when deciding which epics to expand and how to scope stories. |
| Plane/grava IDs | **None.** No cross-refs. |
| Loader | `agents/orchestrator/cli/tech_plan_load.py` (existing; unchanged). |
| Generator behaviour | **Read-only.** Generator never writes this file; operator owns it by hand. |

Useful things for the operator to include: technical goals, deferred areas, architecture constraints, epic-domain notes. Not every epic needs to be listed.

### 7.2 Per-epic tech-plan (new in v2)

```
systems/<SystemName>/business/tech-plan-<epic-slug>.md      ← ONE per epic
```

One file per epic in the system. Filename slug derived from `epic.title` (kebab-case, lowercased, ascii-only). Emitted + updated by the generator on the `techplan` phase. **Distinct artifact** from the system-level free-form `tech-plan.md`.

**Local only.** The generator must never upload this file to a Plane page or set it as a Plane work item's description. See §9 hard limits.

#### Frontmatter schema

```yaml
---
generator_source: <abs path to draft markdown that produced this epic>
generator_run_id: <RID>
plane_project_id: <uuid>
plane_project_code: <e.g. CAPP, STELL>
plane_page_id: <uuid of the spec page the epic was taskified from, if any>
plane_issue_id: <uuid of the Plane work item for this epic>
plane_issue_sequence_id: <int — Plane’s human-readable ID, e.g. 142>
grava_issue_id: <e.g. EPIC-12>
grava_repo_path: <abs path to target repo with .grava>
created_at: <ISO 8601>
updated_at: <ISO 8601>
schema_version: 1
---
```

#### Body structure

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

### 7.3 Per-story spec file (new in v2)

```
systems/<SystemName>/business/stories/<epic-slug>--<story-slug>.md   ← ONE per story
```

One file per story across the system. Filename joins epic-slug + story-slug (`--` separator) so two stories named `login` under different epics don't collide. Emitted + updated by the generator on the `techplan` phase alongside the per-epic file.

**Local only.** Same hard limit as the per-epic file: never uploaded to a Plane page, never sent as a Plane work item description. Engineers own the body.

#### Frontmatter schema

```yaml
---
generator_source: <abs path to draft markdown that produced this epic>
generator_run_id: <RID>
plane_project_id: <uuid>
plane_project_code: <e.g. CAPP, STELL>
plane_page_id: <uuid of the spec page the epic was taskified from, if any>
plane_epic_id: <uuid of the parent Plane epic work item>
plane_issue_id: <uuid of the Plane story work item>
plane_issue_sequence_id: <int — e.g. 153>
grava_epic_id: <e.g. EPIC-12>
grava_issue_id: <e.g. STORY-37>
grava_repo_path: <abs path to target repo with .grava>
epic_slug: <slug>
story_slug: <slug>
created_at: <ISO 8601>
updated_at: <ISO 8601>
schema_version: 1
---
```

#### Body structure (five fixed sections, in order)

```markdown
# <Story title>

> Epic: [<Epic title>](../tech-plan-<epic-slug>.md) · Plane: [<project_code>-<seq>](https://app.plane.so/...) · Grava: `<grava_issue_id>`

## Requirements

<the story description from outline.json — typically "As a … I want … so that …">

## Acceptance Criteria

- <bullet 1 from outline.json story.acceptance_criteria>
- <bullet 2>
- …

## Tech Plan

<generator-empty on create; engineer fills in implementation notes>

## UI/UX Design

- <link or short description from outline.json story.design_links>
- …

## QA Plan

<generator-empty on create; engineer/QA fills in test scenarios, edge cases, fixtures>
```

**Section ownership**:

| Section | Initial source | Re-run behaviour |
|---|---|---|
| `## Requirements` | `story.description_md` from outline | Generator overwrites (regenerated from latest outline) |
| `## Acceptance Criteria` | `story.acceptance_criteria` list | Generator overwrites |
| `## Tech Plan` | empty | **Generator preserves byte-for-byte** (engineer-owned) |
| `## UI/UX Design` | `story.design_links` | Generator overwrites |
| `## QA Plan` | empty | **Generator preserves byte-for-byte** (engineer-owned) |

`## Tech Plan` and `## QA Plan` are the engineer/QA carve-outs (same pattern as `## Tech notes` on the per-epic file). Generator emits the header + a blank line on create; everything inside survives untouched on every subsequent run.

### 7.4 Plane work item description composition

When `taskify` creates a Plane work item (epic, story, or task), the generator composes `description_html` with **four** structured sections — NOT five. QA Plan is local-only and never reaches Plane.

```html
<h2>Requirements</h2>
<p>… story.description_md, or epic.summary, or task title context …</p>

<h2>Acceptance Criteria</h2>
<ul><li>…</li><li>…</li></ul>

<h2>Tech Plan</h2>
<p><em>To be filled by the engineering team.</em></p>

<h2>UI/UX Design</h2>
<ul><li><a href="…">Label</a></li><li>short description …</li></ul>
```

**Per node kind**:

| Section | Epic | Story | Task |
|---|---|---|---|
| Requirements | `epic.summary` if present, else empty placeholder | `story.description_md` | task title + parent story context if known |
| Acceptance Criteria | aggregated from child stories (read-only summary) OR empty | story-level AC list verbatim | empty placeholder |
| Tech Plan | empty placeholder | empty placeholder | empty placeholder |
| UI/UX Design | aggregated from child stories OR empty | story-level design_links | empty placeholder |

Empty sections render their `<h2>` header + a placeholder line (`<p><em>None.</em></p>`) so the structure is consistent across all Plane work items and easy to grep for downstream.

**Critical**: the Plane description is the **only** Plane-side artifact for these sections. There is no link from the Plane work item back to the local per-story / per-epic markdown file. They are two parallel surfaces:

- Engineers edit local md (with QA plan + tech plan) → not synced anywhere.
- PMs/stakeholders read the Plane work item description → fixed at create time + manually updated thereafter.
- Cross-ref: the local md frontmatter carries `plane_issue_id` (one-way lookup local → Plane). Plane has no link back to the local file.

### 7.5 Load semantics — system-level vs per-epic vs per-story

Three loaders, three call sites:

| Loader | When | What it returns | Generator behaviour on miss |
|---|---|---|---|
| `tech_plan_load.py` (existing) | Once at the **start** of a generator run | `{system_name, tech_plan_path, exists}` JSON | Soft-fail. Run continues with no system-level context. Operator warned. |
| `epic_tech_plan_load.py` (new in v2) | Once **per epic** during the `techplan` phase | `{epic_slug, tech_plan_path, exists, frontmatter, generator_body, tech_notes_block}` JSON | Generator emits a fresh file with default body + frontmatter. |
| `story_spec_load.py` (new in v2) | Once **per story** during the `techplan` phase | `{epic_slug, story_slug, story_spec_path, exists, frontmatter, requirements, acceptance_criteria, tech_plan_block, ui_ux_block, qa_plan_block}` JSON | Generator emits a fresh file with the 5 sections. Engineer-owned blocks are empty. |

Algorithm for the per-epic loader:

```
1. Inputs: --target-repo <path>, --system <Name>, --epic-slug <slug>
2. Resolve stellar root via walk-up (same as tech_plan_load.py).
3. Build path = stellar_root / "systems" / <Name> / "business" / "tech-plan-<slug>.md"
4. If exists:
     a. Parse YAML frontmatter.
     b. Split body at the first `## Tech notes` heading.
        - Above-header content = generator-managed
        - From-header onward = engineer-owned, preserved verbatim
     c. Return {exists: true, tech_plan_path, frontmatter, generator_body, tech_notes_block}
5. If not:
     a. Return {exists: false, tech_plan_path}
6. Exit 0 either way (existence is a flag, not an error).
```

Algorithm for the per-story loader (`story_spec_load.py`):

```
1. Inputs: --target-repo <path>, --system <Name>, --epic-slug <slug>, --story-slug <slug>
2. Resolve stellar root via walk-up.
3. Build path = stellar_root / "systems" / <Name> / "business" / "stories" /
                "<epic-slug>--<story-slug>.md"
4. If exists:
     a. Parse YAML frontmatter.
     b. Slice body by H2 headers in fixed order:
        - "## Requirements"        → generator-managed
        - "## Acceptance Criteria" → generator-managed
        - "## Tech Plan"           → engineer-owned (preserve byte-for-byte)
        - "## UI/UX Design"        → generator-managed
        - "## QA Plan"             → engineer-owned (preserve byte-for-byte)
     c. Return all 5 blocks + frontmatter.
5. If not: return {exists: false, story_spec_path}.
6. Exit 0 either way.
```

### 7.6 Write semantics — merge rules

On the `techplan` phase, the generator writes **two** files per story (one per-epic shared by all stories of that epic, one per-story).

**Per-epic file** (`tech-plan-<epic-slug>.md`):

1. Call `epic_tech_plan_load.py`. Get `{exists, frontmatter, generator_body, tech_notes_block}`.
2. Build new content:
   - **Frontmatter**: preserve `created_at` if existing; always rewrite `updated_at` + all `plane_*` / `grava_*` IDs.
   - **Body above `## Tech notes`**: regenerate from outline + post-taskify state. Overwrite.
   - **Body from `## Tech notes` onward**: copy from `tech_notes_block` byte-for-byte. If new, emit `## Tech notes\n\n`.
3. Write atomically (tmp + rename).

**Per-story file** (`stories/<epic-slug>--<story-slug>.md`):

1. Call `story_spec_load.py`. Get `{exists, frontmatter, requirements, acceptance_criteria, tech_plan_block, ui_ux_block, qa_plan_block}`.
2. Build new content (sections in fixed order):
   - **Frontmatter**: preserve `created_at`; always rewrite `updated_at` + all `plane_*` / `grava_*` / `epic_slug` / `story_slug` keys.
   - **`## Requirements`**: regenerate from `story.description_md`. Overwrite.
   - **`## Acceptance Criteria`**: regenerate from `story.acceptance_criteria`. Overwrite.
   - **`## Tech Plan`**: copy `tech_plan_block` byte-for-byte. If new, emit header + blank line.
   - **`## UI/UX Design`**: regenerate from `story.design_links`. Overwrite.
   - **`## QA Plan`**: copy `qa_plan_block` byte-for-byte. If new, emit header + blank line.
3. Write atomically.

These are the only files the generator writes inside `systems/<N>/`. Everything else under `systems/<N>/` (including the free-form system-level `tech-plan.md`) is operator-owned.

**Plane work item description** (separate write surface, not a file):

On `taskify` create, build `description_html` per §7.4 composition table. On idempotent re-run (reconcile path), generator does NOT touch existing `description_html` unless explicitly invoked with `--rewrite-plane-descriptions` (off by default) — Plane is treated as engineer-mutable after create.

### 7.7 Authoring guide

Lives at `docs/generator/tech-plan-format.md` (created in this branch). Covers field semantics, link resolution rules, what happens on epic rename, how to query all tech-plans for a system, and explicit guidance on the system-level vs per-epic split — when to write in each.

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

## 8.5 Run directory + state model

All four write phases share one run directory keyed by `RID` (UTC timestamp by default, overridable via `--run-id`). One run = one Plane page (or one local md source) processed through up to four phases.

### Directory layout

```
<target-repo>/runs/
├── work/<RID>/                          ← per-phase intermediates
│   ├── run.json                         ← {run_id, source, started_at, phases_completed}
│   ├── page.json                        ← from taskify (or stub for source-md mode)
│   ├── preflight.json                   ← Plane types + labels + sentinel lookup
│   ├── ir.json                          ← parsed EpicNode[] from page or source-md
│   ├── dep_graph.json                   ← dependency analyser output
│   ├── plan.json                        ← planner CreateWorkItem ops queue
│   ├── state.json                       ← cross-phase RunState (see schema below)
│   ├── techplan_state.json              ← which per-epic/per-story files written, hashes
│   └── publish_result.json              ← page UUID / URL after publish (if ran)
│
├── preview/<RID>/                       ← human-readable previews (operator approval)
│   ├── master.preview.md                ← consolidated chain preview
│   ├── publish.preview.md               ← which draft → which page
│   ├── taskify.preview.md               ← epic/story/task tree + estimated count
│   ├── mirror.preview.md                ← grava issues to be created
│   └── techplan.preview.md              ← per-epic + per-story files that will be written
│
└── reports/<RID>.json                   ← terminal report (RunReport, all phases)
```

### Cross-phase `RunState` (single source of truth)

```python
@dataclass
class RunState:
    run_id: str
    project_id: str
    page_id: str | None         # None when source-md mode
    source_md_path: str | None  # set when source-md mode
    target_repo: str
    started_at: str             # ISO 8601 UTC
    finished_at: str | None

    # Phase progress: each phase marked done after final op + state write.
    phases_completed: list[str]  # ["publish", "taskify", "mirror", "techplan"]
    phase_in_progress: str | None
    failed_op_index: int | None
    failure_detail: str | None
    rolled_back: bool

    # Resolved IDs (populated incrementally as phases run).
    plane_page_id: str | None           # set by publish (if ran)
    plane_page_url: str | None
    ref_to_plane_uuid: dict[str, str]   # "epic:0", "story:0.1" → Plane work item uuid
    ref_to_plane_seq: dict[str, int]    # → sequence_id
    ref_to_grava_id: dict[str, str]     # → grava issue id

    # Per-phase op-level checkpoints (current task-generator already has these).
    completed_op_indices: list[int]
    plane_relations_posted: list[str]
    plane_comments_posted: list[str]
    dep_edges_posted: list[str]

    # Per-techplan file hashes — operator can verify nothing changed since last run.
    techplan_file_hashes: dict[str, str]  # abs path → sha256
```

Two helper modules read/write this:

- `agents/generator/state.py` — `load_state(path)`, `save_state(state, path)`, atomic write via tmp+rename.
- `agents/generator/cli/init_run.py` (existing) — bootstraps `state.json` on first phase, no-ops on resume.

### Idempotency contract per phase

| Phase | Read | Write | Resume semantics |
|---|---|---|---|
| `publish` | source draft md | Plane page (create or replace), `publish_result.json` | If `state.plane_page_id` set, refuses re-create unless `--replace`. |
| `taskify` | `state.plane_page_id` or `source_md_path`, parses → `ir.json`, plans → `plan.json` | Plane work items, `state.ref_to_plane_uuid`, `state.completed_op_indices` | Skips ops in `completed_op_indices`. Re-runs of completed ops are no-ops via sentinel label diff. |
| `mirror` | `ir.json` + `state.ref_to_plane_uuid` from prior taskify | grava issues, Plane comments, `state.ref_to_grava_id` | Skip-by-grava-id-on-disk; re-runs are no-op. |
| `techplan` | `state.ref_to_plane_uuid` + `state.ref_to_grava_id` | per-epic + per-story md files, `techplan_state.json`, `state.techplan_file_hashes` | Loader merges with existing files; engineer-owned blocks preserved. Generator-managed blocks regenerated. No-op if all hashes match prior run. |

**Critical**: `state.json` is the only file shared across phases. Re-running `mirror` after a successful `taskify` reads `state.ref_to_plane_uuid` and skips the Plane fetch entirely. This is what `--from-taskify-run <RID>` enables.

### Failure surface

```
Phase fails mid-execute → on_failure handler:
  - abort:    state.json captures failed_op_index + failure_detail;
              report written; non-zero exit. No rollback.
  - rollback: phase-specific rollback (Plane delete-in-reverse for taskify;
              grava close-with-comment for mirror; no rollback for techplan).
              state.rolled_back = true.
  - prompt:   interactive y/N/skip; falls through to abort or rollback.

Cross-phase resume:
  - se o generate <phase> --run-id <prior_RID>  ← reads state.json, continues
  - se o generate full ... --run-id <prior_RID> ← resumes the chain
```

---

---

## 9. Hard limits (updated)

The generator’s `AGENT.md` `Hard limits` section becomes:

- **Direct operator entry forbidden for Plane / grava writes.** All write phases (`publish`, `taskify`, `mirror`, `techplan`) only run under `se o generate …`. The bridge script verifies `os.environ.get("STELLAR_ORCH_DISPATCH") == "1"` (set by the orchestrator dispatcher) or refuses with an explanatory error.
- **NEVER process non-`.md` input.** PDF / URL / transcript / codebase frontends are permanently dropped (was deferred).
- **NEVER auto-promote a draft into `systems/<Name>/business/`** without operator approval this turn.
- **NEVER bypass per-phase approval gates.** Each write phase requires explicit `--yes` and a passing dry-run preview.
- **NEVER commit `drafts/`** (gitignored).
- **NEVER overwrite a `## Tech notes` block** on a per-epic tech-plan file. Always copy byte-for-byte from the loaded existing file.
- **NEVER overwrite a `## Tech Plan` or `## QA Plan` block** on a per-story spec file. Same byte-for-byte rule.
- **NEVER sync local per-epic / per-story md files to Plane.** The `publish` phase explicitly refuses any path under `systems/<N>/business/tech-plan-*.md` or `systems/<N>/business/stories/`. These artifacts are local-only by design; the Plane work item description (composed at create via `description_composer.py`) is the only Plane-side surface. Code-enforced via a deny-list in `publish.py`.
- **NEVER include `## QA Plan` content in a Plane work item description.** QA plan is local-only. The `description_composer.py` rejects QA fields from the input dict.

Removed limits (were on the old generator):
- ~~NEVER call Plane API~~
- ~~NEVER call grava~~

---

## 10. Testing strategy

### 10.1 Unit tests

Every migrated module keeps its existing tests under `agents/generator/tests/`. New tests:

| Module | Test file | Key cases |
|---|---|---|
| `publish.py` | `test_publish_cli.py` | upload new page, replace existing page (`--page`), deny-list refuses `systems/<N>/business/` (exit 9), missing source file (exit 1). |
| `taskify.py` | `test_taskify_cli.py` | dry-run preview from Plane page, dry-run preview from `--source-md`, mutex check, full write with `--yes`, resume from prior `--run-id`, rollback on `--on-failure rollback`, idempotent re-run skips completed ops. |
| `mirror.py` | `test_mirror_cli.py` | mirror after taskify, `--from-taskify-run <RID>` resume, re-run no-ops, grava-side rollback. |
| `techplan.py` | `test_techplan.py` | per-epic file emission, per-story file emission, engineer carve-out preservation (`## Tech Plan` + `## QA Plan` + `## Tech notes`), file-hash idempotency, epic-rename self-heal (lookup by `plane_issue_id`). |
| `full.py` | `test_full_chain.py` | full chain ok, fail at each phase + correct resume hint, `publish` skipped when input is Plane page, single `--yes` covers chain. |
| `description_composer.py` | `test_description_composer.py` | 4-section HTML output, QA input rejected (raises), empty placeholders for missing sections, per-node-kind shape (epic/story/task). |
| `story_spec_load.py`, `epic_tech_plan_load.py` | one each | exists/missing split, section boundary parsing, preserves engineer blocks exactly. |
| `plane_search.py` | `test_plane_search.py` | projects / pages / issues search, pagination, auth scope check. |
| `state.py` | `test_state_cross_phase.py` | atomic write, resume round-trip, frontmatter on each phase load. |

### 10.2 Integration tests (sandbox)

End-to-end runs against `stellar-sandbox` (Plane workspace + sibling target repo).

| Scenario | Verifies |
|---|---|
| `se generate <src> --plane-project SANDBOX --plane-page <p>` + edit drafts + `se o generate full --source-md drafts/X.md --yes` | Full workflow: download → edit → publish → taskify → mirror → techplan. |
| Mid-taskify failure (kill Plane API) + resume with `--run-id` | State recovery, op-level checkpoint. |
| `se o generate techplan` against a system that already has engineer-edited `## Tech Plan` blocks | Carve-out preservation byte-for-byte. |
| `se o generate publish drafts/X.md` against a system that has `tech-plan-foo.md` | Deny-list refuses paths under `systems/<N>/business/` (exit 9). |
| Re-run `se o generate full` on same source 24h later (operator made changes to outline) | Reconcile path: skips unchanged, updates only what's diff'd. |

A sandbox harness script lives at `agents/generator/tests/sandbox/e2e.sh` (operator-runnable, not in CI). Documented in `docs/generator/v2-architecture.md`.

### 10.3 Regression

- `grava_plane_sync.py` behaviour unchanged via the existing `tests/cli/test_grava_plane_sync.py` (migrate alongside its module).
- All 276 task-generator tests must pass post-migration with renamed imports.
- Orchestrator routing tests (`test_route.py`, `test_pick_ready.py`) updated for `task-generator` → `generator` team rename.

### 10.4 CI scope

Unit tests run per-PR (`pytest agents/generator/tests/ agents/orchestrator/tests/`). Integration tests are operator-driven against sandbox (no CI auth to Plane). H7 adds a `make smoke-sandbox` target that runs the end-to-end harness with operator-supplied credentials.

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
3. ~~**Per-epic tech-plan vs single-file tech-plan-index?**~~ **Resolved 2026-05-23:** both. System-level free-form `tech-plan.md` (existing) stays as session-context loader. New per-epic `tech-plan-<slug>.md` files added under `systems/<N>/business/`. See §7.
4. **`schema_version` start value** — `1` chosen. Future migration story: when frontmatter shape changes, bump version + add a migration script. OK to ship at v1?
5. **Per-story file path layout.** Plan chose flat `systems/<N>/business/stories/<epic-slug>--<story-slug>.md` to avoid renaming when epic moves. Alternative: nested `systems/<N>/business/<epic-slug>/<story-slug>.md`. Recommendation: flat. Confirm.
6. **Story slug collision on rename.** When an epic is renamed (epic-slug changes), existing per-story files become orphaned by filename. Options: (a) loader treats `plane_issue_id` as the primary key and rewrites filenames on mismatch; (b) operator runs a one-off `se o generate rename-epic` to migrate. Recommendation: (a) — generator self-heals via the Plane ID. Confirm.
7. **Plane "Tech Plan" section at create time.** Per §7.4 it renders as a placeholder (`<em>To be filled by the engineering team.</em>`). Alternative: pull current `## Tech notes` block from the per-epic file (if it exists at create time). Recommendation: placeholder. Engineers update Plane manually; local tech plan stays the source of truth. Confirm.
8. **Re-running `taskify` against a Plane work item that already exists.** The reconcile phase (carried over from current task-generator) updates title + description by default. With structured sections in Plane now, should reconcile rewrite the entire description, or only the `## Requirements` + `## Acceptance Criteria` + `## UI/UX Design` sections (leaving `## Tech Plan` untouched since engineers may have edited it)? Recommendation: leave `## Tech Plan` untouched; reconcile only sync-from-outline-able sections. Confirm.
9. **`STELLAR_ORCH_DISPATCH=1` env-var gate.** Write phases refuse to run unless the orchestrator set this. Alternative: a CLI flag (`--from-orchestrator`) that's clearer in stack traces but easier to spoof. Recommendation: env var — the orchestrator always sets it, and operators trying direct invocation get a fast loud failure. Confirm.
10. **`runs/work/<RID>/` retention.** Today the directory grows unbounded. Should H6 add a `se o generate prune --before <date>` command, or cron a 30-day cleanup? Recommendation: prune command, operator-invoked. Confirm.
11. **Test fixture for sandbox e2e (§10.2).** Should the harness script ship in `agents/generator/tests/sandbox/` (operator runs ad-hoc) or be an explicit `make` target reading credentials from `.env`? Recommendation: shell script + `make smoke-sandbox` target. Confirm.
12. **`se o generate full` failure-recovery UX.** When phase 3 of 4 fails, should the operator see a structured next-step hint (e.g. "Resume with: `se o generate techplan --run-id <RID>`") or just the standard report path? Recommendation: structured hint printed to stderr, plus standard report. Confirm.

---

## 13. Out of scope (explicit non-goals)

- Multi-workspace orchestration (one workspace at a time).
- Streaming / real-time Plane updates (still batch-on-dispatch).
- Generator-side LLM calls (Phase D still deferred — outline.json still manual).
- Auto-resolution of diff on re-run (operator decides; current rule preserved).
- Auto-promote drafts (still manual operator copy).
