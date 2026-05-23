# Grava → Plane sync — operator setup

This guide configures the environment so that Grava agents (coder, reviewer, pr-creator) can locate and invoke `grava_plane_sync.py` after each `grava signal`.

> **Looking for the command reference (flags, modes, exit codes)?** See [`docs/cli/se-plane-sync.md`](cli/se-plane-sync.md). This page covers operator setup only.

## What `STELLAR_ENGINE_HOME` is

A shell environment variable holding the **absolute path to your local stellar-engine checkout**.

The grava agent prompts reference the sync script through this variable:

```bash
python3 "${STELLAR_ENGINE_HOME:-/Users/trungnguyenhoang/IdeaProjects/stellar-engine}/agents/task-generator/cli/grava_plane_sync.py" "$ISSUE_ID" ... || true
```

If unset, the agent falls back to the hard-coded dev-box path (`/Users/trungnguyenhoang/IdeaProjects/stellar-engine`). Setting `STELLAR_ENGINE_HOME` correctly is required for any other machine.

## Setup

### 1. Decide where stellar-engine lives

Clone (or locate) the repo:

```bash
git clone https://github.com/hoangtrungnguyen/stellar-engine.git ~/code/stellar-engine
# OR locate an existing checkout
ls -d ~/code/stellar-engine
```

Note the absolute path.

### 2. Add the export to your shell profile

**zsh** (default on macOS):

```bash
echo 'export STELLAR_ENGINE_HOME="$HOME/code/stellar-engine"' >> ~/.zshrc
source ~/.zshrc
```

**bash**:

```bash
echo 'export STELLAR_ENGINE_HOME="$HOME/code/stellar-engine"' >> ~/.bashrc
source ~/.bashrc
```

**fish**:

```fish
set -Ux STELLAR_ENGINE_HOME $HOME/code/stellar-engine
```

Replace `$HOME/code/stellar-engine` with your actual path.

### 3. Verify

```bash
echo "$STELLAR_ENGINE_HOME"
# expected: /Users/<you>/code/stellar-engine (or wherever you cloned)

test -f "$STELLAR_ENGINE_HOME/agents/task-generator/cli/grava_plane_sync.py" \
  && echo "OK — sync script reachable" \
  || echo "FAIL — path wrong or script missing"
```

### 4. Verify end-to-end with a dry run

The sync script must exit 0 even with no work to do:

```bash
python3 "$STELLAR_ENGINE_HOME/agents/task-generator/cli/grava_plane_sync.py" --help
# prints usage

# Optional: scan all plane-linked issues in a grava repo (no-op if none mirrored)
python3 "$STELLAR_ENGINE_HOME/agents/task-generator/cli/grava_plane_sync.py" \
  --project-id <your-plane-project-uuid> \
  --grava-repo /path/to/your/grava/repo \
  --log-level DEBUG
```

## Related environment variables

The agent invocation also reads two optional overrides — set them in the same shell profile if your project differs from the dev-box default:

| Variable | Purpose | Default in agent prompt |
|---|---|---|
| `STELLAR_ENGINE_HOME` | Path to stellar-engine checkout | `/Users/trungnguyenhoang/IdeaProjects/stellar-engine` |
| `PLANE_PROJECT_ID` | Target Plane project UUID | `8af0f117-1dd0-4bfe-8db8-ff131d865534` (SportBuddies) |
| `GRAVA_REPO` | Path to the Grava repo for the agent's project | `/Users/trungnguyenhoang/IdeaProjects/grava` |

The agent's call site looks like:

```bash
python3 "${STELLAR_ENGINE_HOME:-...}/agents/task-generator/cli/grava_plane_sync.py" \
    "$ISSUE_ID" \
    --project-id "${PLANE_PROJECT_ID:-...}" \
    --grava-repo "${GRAVA_REPO:-...}" \
    --system-yaml "${STELLAR_ENGINE_HOME:-...}/systems/SportBuddies/system.yaml" \
    || true
```

Override any of the three by exporting them; rely on the defaults for the rest.

### Plane credentials

Independent of `STELLAR_ENGINE_HOME`. The sync script reads (in order):

1. `PLANE_API_TOKEN` / `PLANE_WORKSPACE` / `PLANE_HOST` env vars
2. `~/.config/plane/config.json` (created by `bash setup.sh`)

If neither is present, the script silently no-ops (`exit 0`) — agent pipeline is unaffected. You can configure Plane later without touching agent code.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Agent's stderr shows `python3: can't open file '...'` | `STELLAR_ENGINE_HOME` unset and dev-box fallback path doesn't exist on this machine | Export `STELLAR_ENGINE_HOME` in your shell profile |
| Sync exits 0 silently every time | No Plane credentials | Run `bash $STELLAR_ENGINE_HOME/setup.sh` or set `PLANE_API_TOKEN` + `PLANE_WORKSPACE` |
| Sync exits 2 silently | Grava issue has no `plane:<seq>` label | Expected — non-mirrored issues are silently skipped |
| Sync exits 3 (Plane API failure) | Network error, expired token, or 5xx from Plane | Agent ignores via `\|\| true`; retry on next signal |
| State patch doesn't reach Plane | Status name not in `plane_state_map` AND no group fallback match | Add the mapping in `systems/<Name>/system.yaml`'s `plane_state_map` block (keyed by project UUID) |
| Subprocess inherits empty env | `subprocess.run` was called without forwarding `os.environ` | Already handled inside `grava_plane_sync.py`; this only affects custom wrappers |

## CI / non-interactive contexts

For Claude Code orchestrator processes that don't load your shell profile, export the variable in the launching script:

```bash
#!/usr/bin/env bash
export STELLAR_ENGINE_HOME="$HOME/code/stellar-engine"
export GRAVA_REPO="$HOME/code/my-grava-repo"
export PLANE_PROJECT_ID="00000000-0000-0000-0000-000000000000"
exec claude code "$@"
```

Or set them in the systemd / launchd unit file, GitHub Actions step `env:`, or Docker `ENV` directive — wherever the agent process is spawned.
