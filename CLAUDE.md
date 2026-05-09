# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Tooling for managing Plane (project management) from the terminal and Claude Code. Three components:

- **`setup.sh`** — installs `plane` CLI (`@aaronshaf/plane` via bun) and saves credentials to `~/.config/plane/config.json`
- **`sync.py`** — syncs local markdown files to Plane project pages via the Plane REST API; tracks file→page-ID mappings in `.plane-pages.json`
- **`mcp-setup.md`** — instructions for wiring up the Plane MCP server to Claude Code (enables the `mcp__plane__*` tools in this session)

## Setup

```bash
# First-time setup (installs plane CLI + Python deps + saves credentials)
bash setup.sh

# Python deps only
pip install markdown requests
```

Credentials are stored at `~/.config/plane/config.json` (chmod 600):
```json
{ "host": "https://api.plane.so", "workspace": "SLUG", "token": "TOKEN" }
```

Alternatively set env vars: `PLANE_API_TOKEN`, `PLANE_HOST`, `PLANE_WORKSPACE`.

## sync.py usage

```bash
# Sync one file (creates or updates the Plane page)
python3 sync.py <project-uuid> notes.md

# Sync a directory
python3 sync.py <project-uuid> docs/

# Preview without changes
python3 sync.py --dry-run <project-uuid> docs/
```

Page names are derived from the first `# H1` in each markdown file. The mapping of local path → Plane page UUID is persisted in `.plane-pages.json`.

## plane CLI quick reference

```bash
plane projects list
plane issues list <PROJECT_IDENTIFIER>
plane issue create <PROJECT_IDENTIFIER> "Issue title"
```

## MCP server (already active in this session)

The `mcp__plane__*` tools are available directly — no CLI needed for most operations. Use them for creating/updating work items, cycles, modules, etc. See `mcp-setup.md` for connection options (OAuth, API key, or local stdio for self-hosted).

## Architecture notes

- `sync.py` calls `PATCH /api/v1/workspaces/{workspace}/projects/{project}/pages/{id}/` for updates and `POST` for creates; auth header is `X-API-Key`.
- `.plane-pages.json` is the source of truth for which local files have already been pushed — delete an entry to force re-create.
- The plane CLI is a separate bun package (`@aaronshaf/plane`) unrelated to `sync.py`; they share only the `~/.config/plane/config.json` credentials file.
