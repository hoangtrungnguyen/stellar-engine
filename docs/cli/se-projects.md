# `se projects`

Read-only inspection of Plane projects in the active workspace. Four subcommands: `list`, `show`, `members`, `states`. Never writes to Plane or grava.

## Synopsis

```
se projects list    [--include-private] [--json] [--plane-profile NAME | --plane-config PATH]
se projects show    <project_id> [--json] [--plane-profile NAME | --plane-config PATH]
se projects members <project_id> [--json] [--plane-profile NAME | --plane-config PATH]
se projects states  <project_id> [--json] [--plane-profile NAME | --plane-config PATH]
```

`<project_id>` accepts a Plane project UUID **or** a short identifier (e.g. `CAPP`, `STELL`). Codes resolve via the workspace projects listing — same mechanism `se download` and `se pages` use.

## Subcommands

### `list` — workspace projects

Walks `/api/v1/workspaces/<workspace>/projects/` and prints a table sorted by `identifier`.

| Column | Source |
|---|---|
| `IDENTIFIER` | `project.identifier` (e.g. `CAPP`) |
| `NAME` | `project.name` |
| `ID` | `project.id` (UUID) |

**Privacy default**: public projects only (`network == 2`). Pass `--include-private` to also list secret projects (`network == 0`) and other non-public modes. Older Plane schemas without a `network` field are treated as public so nothing silently disappears.

Header shows the count + filter note:

```
Workspace: stellar-sandbox
Projects:  3 of 5 total (public only; 2 private hidden — pass --include-private)
```

### `show <id>` — single project details

Renders a key/value summary:

```
Identifier     CAPP
Name           Court Booking App
ID             cec88b42-b47c-4f1c-bfdf-a882c490a784
Workspace      stellar-sandbox
Network        public
Total members  7
Lead           u-jane
Created        2026-01-01T00:00:00Z
Updated        2026-05-23T00:00:00Z
Description    Reservations for sport courts.
```

Long descriptions (>200 chars) are truncated with `…`. Pass `--json` for the raw project blob.

### `members <id>` — project members

Lists members from `/projects/<id>/members/`. Columns: `ID`, `ROLE`, `NAME`, `EMAIL`. Sorted by role descending (admin first), then by display name.

| Plane role int | Meaning |
|---|---|
| `20` | Admin |
| `15` | Member |
| `10` | Viewer |
| `5` | Guest |

Values vary by Plane version; the column shows the raw int.

### `states <id>` — workflow states

Lists project states from `/projects/<id>/states/`. Columns: `NAME`, `GROUP`, `COLOR`, `ID`. Sorted by **natural pipeline order**: `backlog → unstarted → started → completed → cancelled`, then by `sequence` within each group. Unknown groups sort last alphabetically.

Plane state groups:

| group | typical meaning |
|---|---|
| `backlog` | not yet picked up |
| `unstarted` | ready, no work yet (e.g. Todo) |
| `started` | active (e.g. In Progress) |
| `completed` | done (e.g. Done, Released) |
| `cancelled` | dropped (e.g. Won't Fix, Cancelled) |

## Options

| Flag | Default | Meaning |
|---|---|---|
| `--include-private` | off | `list` only. Widens candidate pool to non-public projects. |
| `--json` | off | Emit raw API JSON instead of the table / key-value summary. |
| `--plane-profile <NAME>` | — | Load creds from `~/.config/plane/<NAME>.json` (overrides the default `config.json`) |
| `--plane-config <PATH>` | — | Load creds from an explicit JSON file path. Overrides `--plane-profile`. |

Credential resolution order (highest → lowest): direct env vars (`PLANE_API_TOKEN`, `PLANE_WORKSPACE`, `PLANE_HOST`) > `--plane-config` > `PLANE_CONFIG` env > `--plane-profile` > `PLANE_PROFILE` env > default `~/.config/plane/config.json`. See [`docs/cli/se-download.md`](./se-download.md#credential-resolution-order-highest--lowest) for the full table.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | project not found (unknown `<id>`) or argparse usage error |
| 2 | API failure (network / 4xx / 5xx) |

## Recipes

```bash
# List every project (just the publics):
se projects list

# Include secret/restricted projects:
se projects list --include-private

# Pipe to jq for scripting:
se projects list --json | jq '.[] | select(.network=="public") | .identifier'

# Sanity-check one project before running se download / se taskgen against it:
se projects show CAPP

# Discover the workflow states a project uses (useful when writing
# system.yaml's plane_state_map for grava_plane_sync):
se projects states CAPP

# Pull the member roster as CSV-ish for an audit:
se projects members CAPP --json \
  | jq -r '.[] | [.id, .role, .member__display_name, .member__email] | @tsv'

# Cross-workspace:
se projects list --plane-profile stellar-sandbox
se projects show STELL --plane-profile stellar-sandbox
```

## Plane API endpoints used

| Subcommand | HTTP | Path (under `/api/v1/workspaces/<workspace>/`) |
|---|---|---|
| `list` | GET | `projects/` |
| `show` | GET | `projects/<id>/` |
| `members` | GET | `projects/<id>/members/` |
| `states` | GET | `projects/<id>/states/` |

Reference: https://developers.plane.so/api-reference/project/list-projects.

## Related commands

- [`se pages <project>`](./se-pages.md) — list pages inside a project. Same `--include-private`/`--json`/`--plane-profile` conventions.
- [`se download <project>`](./se-download.md) — pull pages to local markdown.
- `se taskgen <project> <page>` — write Plane work items from a spec page (destructive).

## What it's **NOT**

- A creator. There is no `se projects create / delete / archive`. To create/delete projects, use the Plane web UI.
- A mutator. `se projects` never PATCHes anything — read-only by design.
- A cross-workspace aggregator. Each invocation hits one workspace; switch via `--plane-profile`.
- A member-manager. Adding/removing members lives in the web UI; `members` only lists.
