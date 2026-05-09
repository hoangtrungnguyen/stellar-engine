# Plane MCP Server — Installation Guide

Connect Plane to Claude Code so you can manage projects, issues, cycles, and modules via natural language.

---

## Prerequisites

| Requirement | Check |
|---|---|
| Claude Code CLI | `claude --version` |
| Node.js 22+ | `node --version` |
| Plane API token | Plane → Profile → Personal Access Tokens |
| Workspace slug | From your Plane URL: `app.plane.so/{workspace-slug}/` |

---

## Option 1 — HTTP + OAuth (recommended for Plane Cloud)

Simplest setup. Authenticates via browser — no token to manage manually.

```bash
claude mcp add --transport http plane https://mcp.plane.so/http/mcp
```

Then inside Claude Code run `/mcp` and follow the browser prompt to authorize.

---

## Option 2 — HTTP + API Token (recommended for CI/CD / automation)

Uses your Personal Access Token directly. Good for scripting or when you want
credentials stored explicitly.

```bash
claude mcp add-json plane '{
  "type": "http",
  "url": "https://mcp.plane.so/http/api-key/mcp",
  "headers": {
    "Authorization": "Bearer YOUR_API_TOKEN",
    "X-Workspace-slug": "YOUR_WORKSPACE_SLUG"
  }
}'
```

Replace `YOUR_API_TOKEN` and `YOUR_WORKSPACE_SLUG` before running.

---

## Option 3 — Local Stdio (self-hosted Plane instances)

Runs the MCP server locally via `uvx`. Required when your Plane instance is not
on `app.plane.so`.

**Prerequisites:** Python 3.10+ and `uvx` (`pip install uvx`)

```bash
claude mcp add-json plane '{
  "type": "stdio",
  "command": "uvx",
  "args": ["plane-mcp-server", "stdio"],
  "env": {
    "PLANE_API_KEY": "YOUR_API_TOKEN",
    "PLANE_WORKSPACE_SLUG": "YOUR_WORKSPACE_SLUG",
    "PLANE_BASE_URL": "https://your-plane-instance.com"
  }
}'
```

---

## Verify Installation

```bash
# List all registered MCP servers
claude mcp list

# Inspect Plane server config
claude mcp get plane
```

Inside Claude Code, run `/mcp` — Plane should appear as connected with a green status.

---

## Available Tools (55+)

| Category | Count | What you can do |
|---|---|---|
| Projects | 9 | List, create, update, delete; manage members & features |
| Work Items | 7 | Create, search, update, delete issues across projects |
| Cycles | 12 | Create sprints, add/remove items, transfer work, archive |
| Modules | 11 | Organise features, associate items, archive modules |
| Initiatives | 5 | Manage workspace-level strategic goals across projects |
| Intake | 5 | Triage incoming requests, accept or reject |
| Work Item Properties | 5 | Configure custom fields and metadata |
| Users | 1 | Get authenticated user info |

---

## Example Natural Language Commands

Once connected, use plain English inside Claude Code:

```
List all projects in my workspace
Create an issue "Fix auth token expiry" with high priority in STELLAR
Move all In Progress issues from cycle Q1 to Q2
Show me all unassigned issues in the SMARTFAC project
Add issue STELLAR-12 to the current sprint
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Server not connecting | `claude --mcp-debug` to see detailed logs |
| OAuth token stale | `rm -rf ~/.mcp-auth` then re-authenticate |
| Request timeout | `MCP_TIMEOUT=10000 claude` to extend timeout |
| Node version error | `node --version` must be 22+; use `nvm install 22` |
| uvx not found (Option 3) | `pip install uvx` or `brew install python@3.11` |

---

## Uninstall

```bash
claude mcp remove plane
```

---

## Resources

- [Official Plane MCP Docs](https://developers.plane.so/dev-tools/mcp-server-claude-code)
- [Plane API Reference](https://developers.plane.so/api-reference/introduction)
- [Model Context Protocol](https://modelcontextprotocol.io)
