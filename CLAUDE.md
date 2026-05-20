# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Stellar Engine is a sibling toolkit that operates on target repos using grava + Plane. It is **not** a fleet manager (yet); it is a collection of sub-agents and CLI scripts that the operator invokes from a Claude Code session.

Three sub-agents and one v0 sync layer make up the core:

- **`agents/generator/`** — turns a markdown source document into reviewable spec drafts under `drafts/<project>/runs/<RID>/`. Five-step pipeline (init_run → extract → outline → render → diff vs prior run). Phase D LLM call is deferred — the outline step today runs manually via a Claude Code session. Never writes to Plane or grava; promotion into `systems/<Name>/business/` is a manual operator step. See [`agents/generator/README.md`](agents/generator/README.md), [`agents/generator/AGENT.md`](agents/generator/AGENT.md), and the full walkthrough in [`docs/generator/usage.md`](docs/generator/usage.md).
- **`agents/task-generator/`** — converts a Plane spec page into a planned epic-story-task hierarchy, writes work items to Plane (with `blocking` relations), and mirrors the hierarchy to Grava in the target repo. Three-phase (preview / Plane / Grava), operator approval per turn. See [`agents/task-generator/AGENT.md`](agents/task-generator/AGENT.md). Phase 6 is current.
- **`agents/orchestrator/`** — routes claimed grava issues to one of four teams: `task-generator` (epics), `fix-bug` (bug-type issues), `epic-task` (task/story → `/ship`), and `qa` (`qa-ready` label). Entry commands: `/deploy`, `/generate`, `/qa`. State persisted via grava wisps. See [`agents/orchestrator/AGENT.md`](agents/orchestrator/AGENT.md).
- **Grava → Plane state sync (v0)** — `agents/task-generator/cli/grava_plane_sync.py` runs after every `grava signal` (coder/reviewer/pr-creator hooks on the grava side). Diffs status/assignee/comments, PATCHes Plane. Non-fatal (`|| true`). See [`docs/grava-plane-sync-setup.md`](docs/grava-plane-sync-setup.md) for `STELLAR_ENGINE_HOME` setup.

Two markdown-sync utilities ship Plane content from disk:

- **`upload_project_pages.py`** — syncs local markdown into Plane project pages. Tracks file → page-ID in `.plane-pages.json`.
- **`upload_wiki_page.py`** — same idea for Plane workspace wiki pages.

## Setup

```bash
# First-time: install plane CLI + Python deps + save credentials
bash setup.sh

# Export STELLAR_ENGINE_HOME so grava agents can locate grava_plane_sync.py
echo 'export STELLAR_ENGINE_HOME="$HOME/IdeaProjects/stellar-engine"' >> ~/.zshrc
source ~/.zshrc
```

Credentials at `~/.config/plane/config.json` (chmod 600):

```json
{ "host": "https://api.plane.so", "workspace": "SLUG", "token": "TOKEN" }
```

Or env: `PLANE_API_TOKEN`, `PLANE_HOST`, `PLANE_WORKSPACE`.

**Multi-workspace**: drop additional files at `~/.config/plane/<name>.json`
(same schema, also chmod 600) and select via `--plane-profile <name>`,
`PLANE_PROFILE=<name>`, or `PLANE_CONFIG=<absolute path>`. Priority:
direct env vars > `PLANE_CONFIG` > `PLANE_PROFILE` > default `config.json`.
Applies to `se taskgen`, `se plane-sync`, `se o {doctor,expand,deploy}`.

For the grava-side hooks (so each `grava signal` mirrors to Plane), see [`docs/grava-plane-sync-setup.md`](docs/grava-plane-sync-setup.md).

## Operator entry points

```bash
# se CLI — engine-level commands
python3 cli/se init                                # scaffold repos.yaml, policies/, logs/
python3 cli/se repos                               # list configured repos (bare = list)
python3 cli/se repos add <name> --path <abs-path>  # register repo + `grava init` if .grava absent
python3 cli/se doctor --dir .                      # validate tools, repos, generator, .env, drafts/
python3 cli/se download <plane-project-uuid>       # pull Plane pages → systems/<workspace>/<project>/
python3 cli/se download CAPP                       # accepts short identifier; resolves to UUID via Plane API
python3 cli/se download CAPP --page-id <uuid>      # fetch only one page (skips the project listing)
python3 cli/se plane-sync [ISSUE_ID] --project-id <uuid> --grava-repo <path> \
    [--system-yaml ... --state-file ... --log-level ... --direction {push,pull,both}]
                                                   # default pull: import all Plane work items as new grava issues
                                                   # push: grava → Plane (status / assignee / comments)
                                                   # both: pull then push
                                                   # NOTE: raw `python3 grava_plane_sync.py` still defaults to push
                                                   # (agent hooks rely on this).

# Generate reviewable spec drafts from a markdown source (no Plane / grava writes)
python3 cli/se generate <source.md>                                  # offline: extract.json only
                                                                     # drafts namespace = source filename stem.
python3 cli/se generate <source.md> --step render                    # render after manual outline.json
python3 cli/se generate --plane-project CAPP --plane-page <page-uuid>
                                                   # source from a Plane page: downloads to
                                                   # systems/<workspace>/<CAPP>/<slug>.md first,
                                                   # then runs the generator chain on it.
                                                   # drafts namespace defaults to the Plane project code (CAPP).
                                                   # Pass --project <name> to override the namespace
                                                   # (and the system H1) in any mode.
# See docs/generator/usage.md for the full walkthrough including manual outline step.

# Generate work items from a Plane spec page (dry-run first)
python3 cli/se taskgen <project_id> <page_id> --dry-run
python3 cli/se taskgen <project_id> <page_id> --yes        # writes Plane + Grava
# (equivalent: python3 agents/task-generator/cli/run.py <project_id> <page_id> --yes)

# Orchestrator: route + dispatch grava issues to teams
# `se o` is a shorthand alias for `se orchestrator` — both forms work identically.
python3 cli/se o route <issue_id> --target-repo <path>
python3 cli/se o pick --team fix-bug --target-repo <path>
python3 cli/se o deploy [<id>] [--team T] --target-repo <path>  # routes + Phase 0 (single)
python3 cli/se o deploy --all --team T --target-repo <path>     # batch: every ready issue on team T
python3 cli/se o expand <epic-id> --target-repo <path>          # epic → task-generator
python3 cli/se o fix-bug claim|verify|pr <id> --target-repo <path>
python3 cli/se o qa load|report <id> --target-repo <path>
python3 cli/se o doctor --target-repo <path>
# (or the raw script: python3 agents/orchestrator/cli/{route,pick_ready,...}.py)

# Sync local markdown to Plane
python3 upload_project_pages.py <project-uuid> docs/
python3 upload_wiki_page.py docs/notes.md
```

## Registry files

- **`repo-map.yaml`** — root mapping: Plane project UUID → `{repo_name, git_url, workspace_prefix}`. Used by `task-generator/cli/resolve_repo.py` to find the sibling repo. Auto-clones if missing.
- **`systems/<Name>/system.yaml`** — per-system override (preferred). Wins on conflict with the root file. Also holds the `plane_state_map` for `grava_plane_sync.py`.
- See [`systems/SportBuddies/`](systems/SportBuddies) for a complete system spec template.

## PR merge watcher (cron)

`agents/orchestrator/scripts/pr_merge_watcher.sh` polls grava issues labeled `pr-created`. Handles MERGED (close + signal), CLOSED (label `pr-rejected`, re-entry hint), OPEN (stale cap at 72h, new-comment detection). Install as cron in the target repo:

```bash
*/5 * * * * cd /path/to/target-repo && \
    bash /path/to/stellar-engine/agents/orchestrator/scripts/pr_merge_watcher.sh
```

## MCP wiring

`mcp__plane__*` tools work directly in this session. See [`mcp-setup.md`](mcp-setup.md) for OAuth / API-key / self-hosted stdio options. `mcp-setup.md` covers connection; the agents above own actual writes.

## Architecture notes

- **Wisps are the state machine.** Every pipeline transition writes a grava wisp (`pipeline_phase`, `team`, `orchestrator_heartbeat`, `pr_url`, …). CLI scripts are stateless and re-run safely; they read wisps before doing work.
- **Approval per turn for destructive Plane / Grava writes.** task-generator's three phases each require operator approval in the current Claude turn — "yes earlier today" does not count.
- **Two registries, distinct purposes.** `repo-map.yaml` is for task-generator (UUID → repo). A future `repos.yaml` will hold fleet-runtime config (repo name → poll interval, concurrency, etc.). Do not merge them.
- **task-generator never writes Plane `state`.** That field is owned by `grava_plane_sync.py` only.
- **Main system vs support systems.** The company has one designated **main system** (primary codebase) and one or more **support systems** (external integrations). The root `repo-map.yaml` and root Plane configuration belong to the main system. All `se` commands default to the main system — support systems must be targeted explicitly via their own `system.yaml`. See [`systems/CLAUDE.md`](systems/CLAUDE.md) for the systems index and conventions.

## Key documents

| Doc | Topic |
|:---|:---|
| [`README.md`](README.md) | End-user install + quick start |
| [`docs/install.md`](docs/install.md) | Binary build + release flow (PyInstaller + GH Actions) |
| [`docs/stellar-engine/strategy.md`](docs/stellar-engine/strategy.md) | System-wide design and roadmap |
| [`docs/stellar-engine/plan.md`](docs/stellar-engine/plan.md) | Open gaps and phase-by-phase plan |
| [`docs/ship-bug/strategy.md`](docs/ship-bug/strategy.md) | `/ship-bugfix` (fix-bug team) pipeline design |
| [`docs/ship-bug/plan.md`](docs/ship-bug/plan.md) | Concrete steps to formalize fix-bug as a standalone skill |
| [`docs/grava-plane-status-sync-plan.md`](docs/grava-plane-status-sync-plan.md) | v0 (shipped) + v0.1 outline for grava → Plane sync |
| [`docs/grava-plane-sync-setup.md`](docs/grava-plane-sync-setup.md) | Operator setup: `STELLAR_ENGINE_HOME`, shell profile, verification |
| [`docs/self-host/self-host-plane-plan.md`](docs/self-host/self-host-plane-plan.md) | Plan for running Plane locally |
| [`docs/generator/usage.md`](docs/generator/usage.md) | Generator agent — full operator walkthrough (markdown → Plane → grava) |
| [`docs/generator/plan.md`](docs/generator/plan.md) | Generator agent — phase-by-phase implementation plan + status |
| [`docs/generator/epic-dependencies.md`](docs/generator/epic-dependencies.md) | Authoring guide for `## Epic dependencies` Mermaid graphs (grammar, label normalisation, fan-out examples, anti-patterns) |
| [`agents/generator/README.md`](agents/generator/README.md) | Generator agent — quick reference |
| [`docs/task-generator/`](docs/task-generator) | 11 design docs for task-generator (parser, planner, writers, data-model, …) |
| [`docs/repository-folder-level-orchestrator/ORCHESTRATOR_AGENT.md`](docs/repository-folder-level-orchestrator/ORCHESTRATOR_AGENT.md) | In-repo orchestrator design (predecessor of `agents/orchestrator/`) |

## What this repo is NOT

- A fleet manager — `stellar-orchestrator` (continuous-loop fleet runtime) is planned, not built. The `cli/se` operator CLI ships today with `init`, `repos`, `doctor`, `download`, `generate`, `taskgen`, `plane-sync`, and `orchestrator` / `o` (one-shot route/pick/deploy/expand + fix-bug + qa phase wrappers; `se o` is the shorthand alias). See [`docs/orchestrator/daemon-plan.md`](docs/orchestrator/daemon-plan.md) for the daemon plan.
- A general task runner — scope is `grava` + `Plane` + `/ship` only.
- A grava replacement — operates on grava via `--target-repo` flag; never modifies grava's data model except through wisps.
- An LLM-driven spec writer — the Generator agent's outline step (Phase D) is deferred; today the operator hand-writes `outline.json` via a Claude Code session. The agent never calls the Anthropic API directly until Phase D ships.
