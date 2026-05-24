# `se plane-sync`

Bidirectional state sync between a local Grava repo and a Plane.so project. Title, description, priority, status, assignee, and comments can all move in one or both directions depending on the `--direction` flag.

## Synopsis

```
se plane-sync [<issue_id>]
              --project-id <UUID>
              --grava-repo <PATH>
              [--direction {push | pull | both}]
              [--state-file <PATH>]
              [--system-yaml <PATH>]
              [--log-failures <PATH>]
              [--log-level {DEBUG | INFO | WARNING | ERROR}]
              [--plane-profile <NAME> | --plane-config <PATH>]
```

## Modes (`--direction`)

| Mode | Default? | What flows | Skipped scope |
|---|---|---|---|
| `pull` | **yes** for `se plane-sync` | Plane → Grava. Walks every Plane work item in the project; creates a Grava issue for any item not yet labeled `plane:<seq>` in the local repo. | Already-mirrored items (label-matched). Flat structure — every Plane item lands as a Grava `task`, regardless of Plane type (Epic / Story / Task). Hierarchy is **not** reconstructed. |
| `push` | (default for raw `grava_plane_sync.py` called by hooks) | Grava → Plane. For each Grava issue carrying a `plane:<seq>` label, PATCHes the linked Plane work item with the current Grava status (mapped via `plane_state_map`), assignee, and any new comments. | Grava issues without a `plane:<seq>` label (silent no-op). |
| `both` | — | `pull` first, then `push`. | Same skip semantics as each individual mode. |

### Known gap — pull does not refresh existing items

`pull` mode skips already-mirrored items entirely (`if seq in mirrored_seqs: continue`). If a Plane work item's status or title changes after first import (e.g. another teammate edits the work item in the Plane UI on another machine), `se plane-sync --direction pull` will NOT propagate that change into the local Grava repo.

Today's workarounds:
- Trigger a fresh `se taskgen` run against the same spec page. Phase 2 reconcile path detects drift and PATCHes Grava titles + descriptions + priority. Status reconcile is still grava-side only.
- Edit Grava locally, then `--direction push` to make Plane match.

A future `--sync` mode (covered in `docs/generator/absorb-taskgen-plan.md` §5.6) will close this gap.

## Arguments

| Arg | Required | Purpose |
|---|---|---|
| `<issue_id>` | optional | Single Grava issue id (e.g. `grava-0305`) to limit the run. Omit to scan all `plane:<seq>`-labeled issues. Only meaningful for `--direction push` (or the push leg of `both`); ignored on `pull`. |

## Options

| Flag | Default | Meaning |
|---|---|---|
| `--project-id <UUID>` | (required) | Plane project UUID. Source of truth for which Plane workspace and project to talk to. |
| `--grava-repo <PATH>` | (required) | Absolute path to the local Grava repo root. Must contain `.grava.yaml` and `.grava/dolt/`. |
| `--direction {push,pull,both}` | `pull` | See **Modes** above. |
| `--state-file <PATH>` | `~/.local/share/grava-plane-sync/<project_id>.json` | JSON state file caching Plane state-name → group mappings and last-seen sequence ids. Per-project. Created on first run. |
| `--system-yaml <PATH>` | (auto-resolved) | Path to `systems/<Name>/system.yaml` carrying the `plane_state_map` block. Auto-resolves from `<grava-repo>` via the systems index when omitted. |
| `--log-failures <PATH>` | `~/.local/share/grava-plane-sync/errors.jsonl` | Append-only JSONL log of non-success gates (`no_creds`, `no_internet`, `db_init`, `db_query`, `plane_creds`, `no_plane_label`, `plane_api`, `save_state`). Pass `/dev/null` to disable. `se doctor` warns on entries in the last 24h. |
| `--log-level {DEBUG,INFO,WARNING,ERROR}` | `INFO` | Standard Python logging verbosity. `DEBUG` is recommended when troubleshooting state-map fallbacks. |
| `--plane-profile <NAME>` | — | Load creds from `~/.config/plane/<NAME>.json` instead of the default `config.json`. |
| `--plane-config <PATH>` | — | Load creds from an explicit JSON file path. Overrides `--plane-profile`. |

### Credential resolution order (highest → lowest)

1. Direct env vars (`PLANE_API_TOKEN`, `PLANE_WORKSPACE`, `PLANE_HOST`) — each takes precedence individually.
2. `--plane-config <PATH>` flag.
3. `PLANE_CONFIG` env var (absolute path to a JSON file).
4. `--plane-profile <NAME>` flag.
5. `PLANE_PROFILE` env var → `~/.config/plane/<NAME>.json`.
6. Default `~/.config/plane/config.json`.

If neither env nor config file resolve, the script **silently no-ops with exit 0** — the grava-hook pipeline is unaffected.

## How status maps between Grava and Plane

The `plane_state_map` block in `systems/<Name>/system.yaml` is the operator-authored mapping. Keys are Grava-side state names; values are Plane state display names from the project's state list.

```yaml
plane_state_map:
  open:                "Backlog"
  in_progress:         "In Progress"
  code_review:         "In Review"
  changes_requested:   "In Progress"
  pr_open:             "In Review"
  done:                "Done"
  halted:              "Backlog"
```

When the map doesn't have an exact name match, the script falls back to Plane state **group** (one of `backlog | unstarted | started | completed | cancelled`) so default Plane workspaces work out of the box.

The Grava-side state is computed from:

| Grava signal | Source key |
|---|---|
| `status == closed` | `done` |
| `status == in_progress` + label `code_review` | `code_review` |
| `status == in_progress` + label `changes_requested` | `changes_requested` |
| `status == in_progress` + label `pr_open` | `pr_open` |
| `status == in_progress` (no review labels) | `in_progress` |
| `status == open` | `open` |
| Any `tg:state:<name>` label | manual override — wins over computed key |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success or silent no-op (no creds, no internet, no `plane:<seq>` label on the target issue). |
| 1 | Configuration error (bad `--project-id`, unreadable `--grava-repo`, bad `--system-yaml`). |
| 2 | Grava issue not found (with explicit `<issue_id>`). |
| 3 | Plane API failure (4xx other than 404, or 5xx after retries). Agent hooks invoke with `|| true` so this is non-fatal for the grava pipeline. |

## Examples

### Pull all Plane work items into Grava (first-time import)

```bash
se plane-sync \
    --project-id 8af0f117-1dd0-4bfe-8db8-ff131d865534 \
    --grava-repo ~/code/sportbuddies-app
# default --direction pull
```

Creates a flat Grava issue per Plane work item that does not already carry a `plane:<seq>` label. Re-runs are safe; existing items are skipped.

### Push a single Grava issue's state to Plane

```bash
se plane-sync grava-0305 \
    --project-id 8af0f117-1dd0-4bfe-8db8-ff131d865534 \
    --grava-repo ~/code/sportbuddies-app \
    --direction push
```

This is exactly the call shape the auto-installed `.grava/hooks/plane-sync.sh` makes after each `grava signal`.

### Bidirectional reconcile

```bash
se plane-sync \
    --project-id 8af0f117-1dd0-4bfe-8db8-ff131d865534 \
    --grava-repo ~/code/sportbuddies-app \
    --direction both
```

Runs `pull` (import any new Plane items), then `push` (send local Grava state changes back to Plane). Convenient after a multi-day gap; not recommended on every hook fire (slower than push alone).

### Multi-workspace selection

```bash
# Profile: ~/.config/plane/stellar-sandbox.json
se plane-sync \
    --project-id 8af0f117-... \
    --grava-repo ~/code/sportbuddies-app \
    --plane-profile stellar-sandbox \
    --direction both
```

## Operator setup

For the grava-side hook that runs `--direction push` after each `grava signal`, see [`docs/grava-plane-sync-setup.md`](../grava-plane-sync-setup.md). That doc covers `STELLAR_ENGINE_HOME` setup, the hook shim, and verification.

## Optional: `grava_id` custom property mirror

`se plane-sync --direction push` will automatically mirror each Grava issue's ID into a Plane custom property named **`grava_id`**, when one is attached to the work-item type. Setup is **opt-in** — the mirror is a no-op until the property exists in Plane.

### Why

Until now the grava → Plane back-link was a `plane:<seq>` label on the Grava side only. Plane had no field pointing back. With `grava_id` on the Plane side, both systems carry the cross-reference natively, enabling:

- Filters/searches in Plane by Grava ID.
- Pull-side imports (`--direction pull`) that preserve the upstream Grava ID instead of auto-generating a fresh one. Requires grava `--id` support, shipping separately.

### Enable

1. In the Plane web UI: **Settings → Work item types → \<type\> → Properties**.
2. Add a property:
   - **Name**: `grava_id` (case-insensitive; `Grava_ID`, `GRAVA_ID` also work).
   - **Type**: **Text** (single-line).
   - **Required**: off (mirror back-fills lazily).
3. Repeat for every type you want mirrored (typically `Epic`, `Story`, `Task`).
4. Next `se plane-sync … --direction push` run resolves the property UUID per type and starts upserting. Resolved UUIDs are cached in the state file (`~/.local/share/grava-plane-sync/<project_id>.json` under `grava_id_property_uuids`) so subsequent runs skip the discovery step.

The mirror is **idempotent**: each issue's last-posted value is also cached (`grava_id_posted`), so a repeat sync with no change is a no-op (zero API calls per issue).

### Failure semantics

- Property not configured for a type → silent skip for items of that type.
- `list_work_item_types` or `list_type_properties` fails → mirror disabled for the run; logged as warning. Next run retries.
- `upsert_property_value` fails for a single item → logged, mirror returns to caller as non-fatal; the rest of the push continues. Cache is NOT updated for that issue, so the next run retries.

This matches the broader rule for `plane-sync`: nothing in the mirror layer is allowed to fail the surrounding push.

## Implementation pointers

- **Module**: [`agents/task-generator/cli/grava_plane_sync.py`](../../agents/task-generator/cli/grava_plane_sync.py)
- **Hook shim** (auto-installed by `se repos add`): `<grava-repo>/.grava/hooks/plane-sync.sh`
- **Hook env file**: `<grava-repo>/.grava/hooks/plane-sync.env` (chmod 0600) — sets `PLANE_PROJECT_ID`, `GRAVA_REPO`, `SYSTEM_YAML`.
- **State file**: `~/.local/share/grava-plane-sync/<project_id>.json` (per project; safe to delete to force re-cache of Plane state list).

## Related commands

| Command | When to use |
|---|---|
| `se taskgen` | First-time creation: spec page → Plane work items + Grava mirror in one shot. `plane-sync` is the ongoing state reconciler that runs afterwards. |
| `se download` | Pull Plane **pages** (markdown content) — distinct from work items. Read-only; never writes back. |
| `se o doctor --target-repo <path>` | Sanity check on hook installation, state file freshness, and recent failure log entries. |

## Note: raw script vs `se` subcommand

The grava-side hooks call `agents/task-generator/cli/grava_plane_sync.py` directly (not through `se plane-sync`). The raw script's default for `--direction` is `push` (matching what hooks need); the `se plane-sync` wrapper flips that to `pull` (matching the more common operator use case). Both share the same flag set and behaviour otherwise.
