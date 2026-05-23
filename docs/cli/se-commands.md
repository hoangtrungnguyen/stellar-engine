# `se` commands — full reference by use case

Single-page index of every `se` subcommand grouped by what you want to do.
For deep dives on individual commands, see the sibling docs in this folder
(`se-download.md`, `se-plane-sync.md`, `se-projects.md`).

## 1. Setup / bootstrap

| Command | Purpose |
|---|---|
| `se init` | Scaffold `repos.yaml`, `policies/`, `logs/`, `.env.example`. Preserves any existing registered repos. |
| `se repos list` | List repos registered in `repos.yaml`. |
| `se repos add <name> --path <abs-path>` | Register a repo + `grava init` if `.grava/` absent + install orchestrator slash commands. |
| `se doctor [--dir .]` | Validate tools (`grava`, `python3`, `git`), repos, generator agent, `.env`, and `drafts/`. |

## 2. Plane inspection (read-only)

| Command | Purpose |
|---|---|
| `se projects list [--include-private] [--json]` | Workspace projects table. Default = public only. |
| `se projects show <id>` | Single project's key/value summary. |
| `se projects members <id>` | Project members (admin/member/viewer/guest). |
| `se projects states <id>` | Workflow states sorted backlog → cancelled. |
| `se pages --project <id> [--include-private] [--json]` | List pages in a project. |
| `se download <project>` | Pull all public pages → `systems/<workspace>/<project>/`. |
| `se download <project> --page-id <uuid>` | Fetch one page by UUID. |
| `se download <project> --page-name "Foo"` | Fetch one page by exact name. |

Full reference:
- [`docs/cli/se-projects.md`](se-projects.md)
- [`docs/cli/se-download.md`](se-download.md)

## 3. Spec → work items (writes Plane + Grava)

| Command | Purpose |
|---|---|
| `se taskgen <project> <page> --dry-run` | Preview the plan only. No writes. |
| `se taskgen <project> <page> --yes` | Full pipeline: Plane epics/stories/tasks + `blocking` relations + Grava mirror + dep edges. |
| `se taskgen <project> <page> --yes --no-grava` | Plane only — skip Grava mirror. |
| `se taskgen <project> <page> --yes --no-plane-relations` | Skip Phase 6 (no Plane `blocking` posts). |
| `se taskgen … --target-repo DIR` | Override `repo-map.yaml` lookup. |
| `se taskgen … --json-report PATH` | Dump JSON run summary. |
| `se taskgen … --run-id ID` | Override default UTC-timestamp run id. |

Dependency-handling flags: `--no-dep-reorder`, `--allow-dep-cycles`, `--strict-deps`, `--allow-duplicate-pages`.

Failure policy: `--on-failure prompt|rollback|abort`.

Full design: [`agents/task-generator/AGENT.md`](../../agents/task-generator/AGENT.md).

## 4. Grava ↔ Plane sync

| Command | Purpose |
|---|---|
| `se plane-sync [ISSUE_ID] --project-id <uuid> --grava-repo <path>` | Default `--direction pull` — import Plane work items as new Grava issues. |
| `… --direction push` | Grava → Plane (status / assignee / comments). Called by `.grava/hooks/plane-sync.sh` after every `grava signal`. |
| `… --direction both` | Pull, then push. |
| `… --state-file PATH` | Override default state file location. |
| `… --system-yaml PATH` | Path to `system.yaml` with `plane_state_map`. |
| `… --log-level DEBUG\|INFO\|WARNING\|ERROR` | Log verbosity. |

Full reference: [`docs/cli/se-plane-sync.md`](se-plane-sync.md).

## 5. Orchestrator (alias: `se o`)

### 5a. Fleet operations

| Command | Purpose |
|---|---|
| `se o doctor [--target-repo PATH]` | Verify env for orchestrator sub-pipelines + grava→Plane sync. |
| `se o tech-plan [--target-repo PATH]` | Resolve tech plan path for the current target repo. |
| `se o route <id> --target-repo PATH` | Classify an issue's team. |
| `se o pick --team T [--limit N] [--target-repo PATH]` | List next ready issues for a team (JSON). |
| `se o expand <epic-id> [--target-repo PATH] [--dry-run]` | Delegate a grava epic to task-generator. |
| `se o deploy --repo NAME [<id>] [--team T]` | Route + fire Phase 0 (opens tmux + claude session). |
| `se o deploy --repo NAME --all --team T [--limit N] [--stop-on-error]` | Batch: every ready issue on the team. |
| `se o deploy … --dry-run` | Route only, no Phase 0. |
| `se o deploy … --detach` | Background tmux session, don't attach. |
| `se o run [--once] [--repos PATH] [--policies DIR] [--max-concurrent N]` | Fleet daemon (D0 stub today). |
| `se o pr-watch --once [--repo PATH]` | One-shot PR-lifecycle tick (replaces `pr_merge_watcher.sh`). |

### 5b. Per-team phase wrappers (invoked by team agents)

| Command | Phase |
|---|---|
| `se o epic-task claim <id>` | Phase 0: claim story/task + worktree + tech plan. |
| `se o fix-bug claim <id>` | Phase 0: claim bug + worktree. |
| `se o fix-bug verify <id> [--skip-verify] [--state-file]` | Phase 2: self-verify (tests / lint / build). |
| `se o fix-bug pr <id> [--title] [--draft]` | Phase 3: push branch + open PR. |
| `se o qa load <id> [--checklist] [--type cli\|api\|web\|mobile] [--out]` | Phase 0: resolve + stage checklist. |
| `se o qa report <id> --results-file PATH` | Phase 2: render + post QA report. |

## Cross-cutting flags

Most Plane-touching commands accept the same profile resolution flags:

| Flag | Effect |
|---|---|
| `--plane-profile NAME` | Load creds from `~/.config/plane/<NAME>.json`. |
| `--plane-config PATH` | Explicit JSON file path. Overrides `--plane-profile`. |

Resolution priority (highest → lowest): direct env vars (`PLANE_API_TOKEN`, `PLANE_WORKSPACE`, `PLANE_HOST`) > `--plane-config` > `PLANE_CONFIG` env > `--plane-profile` > `PLANE_PROFILE` env > default `~/.config/plane/config.json`.

`.env` at the engine root is auto-loaded for every subcommand except `init`.

## Surface count

- 9 top-level subcommands: `init`, `repos`, `doctor`, `download`, `pages`, `projects`, `taskgen`, `plane-sync`, `orchestrator` (alias: `o`)
- 2 `repos` sub: `list`, `add`
- 4 `projects` sub: `list`, `show`, `members`, `states`
- 11 `orchestrator` sub: `route`, `pick`, `doctor`, `expand`, `tech-plan`, `deploy`, `run`, `pr-watch`, `epic-task`, `fix-bug`, `qa`
- 6 phase-leaf sub: `epic-task claim`; `fix-bug {claim, verify, pr}`; `qa {load, report}`

Total: 30 invokable surfaces.

## Related docs

- [`README.md`](../../README.md) — install + quick start
- [`CLAUDE.md`](../../CLAUDE.md) — architecture + operator entry points
- [`docs/install.md`](../install.md) — binary build + release flow
- [`docs/cli/se-download.md`](se-download.md) — `se download` deep dive
- [`docs/cli/se-projects.md`](se-projects.md) — `se projects` deep dive
- [`docs/cli/se-plane-sync.md`](se-plane-sync.md) — `se plane-sync` deep dive
- [`agents/task-generator/AGENT.md`](../../agents/task-generator/AGENT.md) — taskgen pipeline phases
- [`agents/orchestrator/AGENT.md`](../../agents/orchestrator/AGENT.md) — orchestrator routing + teams
