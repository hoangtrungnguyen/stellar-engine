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

For the grava-side hooks (so each `grava signal` mirrors to Plane), see [`docs/grava-plane-sync-setup.md`](docs/grava-plane-sync-setup.md).

## Operator entry points

```bash
# se CLI — engine-level commands
python3 cli/se init                                # scaffold repos.yaml, policies/, logs/
python3 cli/se repos                               # list configured repos
python3 cli/se doctor --dir .                      # validate tools, repos, generator, .env, drafts/
python3 cli/se download <plane-project-uuid>       # pull Plane pages → systems/<workspace>/<project>/

# Generate reviewable spec drafts from a markdown source (no Plane / grava writes)
python3 cli/se generate <source.md> --project <name>                 # offline: extract.json only
python3 cli/se generate <source.md> --project <name> --step render   # render after manual outline.json
# See docs/generator/usage.md for the full walkthrough including manual outline step.

# Generate work items from a Plane spec page (dry-run first)
python3 cli/se taskgen <project_id> <page_id> --dry-run
python3 cli/se taskgen <project_id> <page_id> --yes        # writes Plane + Grava
# (equivalent: python3 agents/task-generator/cli/run.py <project_id> <page_id> --yes)

# Route + dispatch a single grava issue
python3 agents/orchestrator/cli/route.py <issue_id> --target-repo <path>
# (orchestrator picks team and runs fix-bug / qa / task-generator / epic-task)

# Manually probe ready backlog per team
python3 agents/orchestrator/cli/pick_ready.py --team fix-bug --target-repo <path>

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
| [`agents/generator/README.md`](agents/generator/README.md) | Generator agent — quick reference |
| [`docs/task-generator/`](docs/task-generator) | 11 design docs for task-generator (parser, planner, writers, data-model, …) |
| [`docs/repository-folder-level-orchestrator/ORCHESTRATOR_AGENT.md`](docs/repository-folder-level-orchestrator/ORCHESTRATOR_AGENT.md) | In-repo orchestrator design (predecessor of `agents/orchestrator/`) |

## What this repo is NOT

- A fleet manager — `stellar-orchestrator` (continuous-loop fleet runtime) is planned, not built. The `cli/se` operator CLI ships today with `init`, `repos`, `doctor`, `download`, `generate`.
- A general task runner — scope is `grava` + `Plane` + `/ship` only.
- A grava replacement — operates on grava via `--target-repo` flag; never modifies grava's data model except through wisps.
- An LLM-driven spec writer — the Generator agent's outline step (Phase D) is deferred; today the operator hand-writes `outline.json` via a Claude Code session. The agent never calls the Anthropic API directly until Phase D ships.
