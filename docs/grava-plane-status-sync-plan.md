# Plan — Grava coding team → Plane status sync

## Goal

When the grava coding team transitions an issue's state (claim, code-review,
PR open, merge, halt), the **linked Plane work item's status follows
automatically**. One-way sync, Grava → Plane.

## Inventory: existing grava agent team

Found in `/Users/trungnguyenhoang/IdeaProjects/grava/.claude/agents/`:

| Agent | Trigger | Emits signal | Today's effect on Plane |
|---|---|---|---|
| **planner** | `/plan <doc>` | `PLANNER_NEEDS_INPUT` | None (writes grava issues only) |
| **coder** | claimed task | `CODER_DONE` / `CODER_HALTED` | None |
| **reviewer** | post-coder | `REVIEWER_APPROVED` / `REVIEWER_BLOCKED` | None |
| **pr-creator** | post-review | `PR_DONE` / `PR_FAILED` | None |
| **bug-hunter** | scheduled audit | `BUG_HUNT_COMPLETE` | None |

The cross-link Grava ⇄ Plane already exists: every Grava issue mirrored by
task-generator carries a `plane:<seq>` label (Phase 3). Reverse lookup is
"find Plane work item where `sequence_id == seq`".

## Trigger model — three options

1. **Per-agent signal hooks (recommended for v0).** Each Claude agent
   (`coder`, `reviewer`, `pr-creator`) calls a stellar-engine helper script
   after emitting its `grava signal`. The helper does the Plane PATCH.
   *Pros:* no grava-binary changes; each agent already shells out to `grava`,
   so adding one extra script line is cheap. *Cons:* every agent prompt grows
   by ~5 lines; the duplicate at `plugins/grava/agents/` must mirror.

2. **Grava lifecycle hook.** Wire `grava hook` to fire on every status
   transition. *Pros:* single integration point; agents untouched. *Cons:*
   needs grava-binary change + knowing exactly what events fire when.

3. **Polling reconciler.** Periodic `sync_plane_status.py` walks grava
   issues with `plane:*` labels and reconciles each. *Pros:* zero agent
   changes. *Cons:* lag; adds cron infra.

**v0 ships Option 1.** Option 3 can layer in later as a safety net.

## Components

### 1. New helper — `agents/task-generator/cli/sync_plane_status.py`

```
sync_plane_status.py <grava_issue_id> [--plane-state STATE] [--auto] [--target-repo PATH]
```

- `--auto` (default): read grava issue's `status` + labels, compute target
  Plane state via the system's `plane_state_map`, PATCH Plane.
- `--plane-state STATE`: skip auto-resolution; force Plane to this state name.

**Internals:**
1. `grava show <id> --json` → extract `status`, `labels`, `plane:<seq>` label.
2. If no `plane:<seq>` label → exit 0 silently (non-mirrored grava issue).
3. Resolve the system from `--target-repo` (or grava repo cwd) → find which
   `systems/<Name>/system.yaml` it belongs to → read `plane_state_map`.
4. Compute the source key:
   - `closed` status → key `done`
   - `in_progress` + label `code_review` → key `code_review`
   - `in_progress` + label `changes_requested` → key `changes_requested`
   - `in_progress` + label `pr_open` (or just `pr_open` status) → key `pr_open`
   - `in_progress` (no review label) → key `in_progress`
   - `open` → key `open`
   - manual override: any `tg:state:<name>` label wins (escape hatch).
5. Look up Plane work item: `client.search_work_items(project_id, …)` filtered
   on the existing sentinel `tg:src:<page_id>` set (Phase 4 work — reuse
   `_fetch_existing_with_label`), then match on `sequence_id == seq`.
6. Look up Plane state UUID: `client.list_states(project_id)` (new endpoint
   wrapper), match by name from `plane_state_map`.
7. `client.update_work_item(project_id, work_item_uuid, {"state": state_uuid})`.

**Exit codes:** 0 = synced (or no-op), 1 = config error, 2 = grava issue not
found, 3 = Plane API failure (non-fatal — agents call with `|| true`).

### 2. New Plane client method — `list_states`

```python
def list_states(self, project_id: str) -> list[dict]:
    # GET /workspaces/{ws}/projects/{p}/states/
    # Returns [{id, name, group, ...}]; cached per run.
```

`group` values are Plane's coarse categorization: `backlog | unstarted |
started | completed | cancelled`. Useful as a fallback when state name
doesn't match (e.g. "Done" vs "Completed" vs "Closed").

### 3. State map config — extend `systems/<Name>/system.yaml`

```yaml
projects:
  "<uuid>": { repo_name: ..., git_url: ..., workspace_prefix: ... }

plane_state_map:
  open:                "Backlog"
  in_progress:         "In Progress"
  code_review:         "In Review"
  changes_requested:   "In Progress"   # back to active work
  pr_open:             "In Review"
  done:                "Done"
  halted:              "Backlog"
```

If absent, the helper falls back to Plane state *group* (`unstarted` /
`started` / `completed`), which works on default Plane workspaces.

### 4. Agent integration — one line each

**coder.md** (after CODER_DONE / CODER_HALTED signal):

```bash
# Plane status sync (best-effort, non-fatal)
python3 "${STELLAR_ENGINE_HOME:-/Users/trungnguyenhoang/IdeaProjects/stellar-engine}/agents/task-generator/cli/sync_plane_status.py" \
    "$ISSUE_ID" --auto || true
```

**reviewer.md** (after REVIEWER_APPROVED / REVIEWER_BLOCKED):

Same one-liner. The helper reads the freshly-applied `code_review` /
`changes_requested` label and maps it correctly.

**pr-creator.md** (after PR_DONE):

Same one-liner. Reads PR-opened state, maps to "In Review" (or whatever the
`plane_state_map.pr_open` says).

**On `grava close` (PR merge → done):**
- v0: operator runs sync manually after merge.
- v0.1: wire into the `/ship` orchestrator's close path.

Each agent's prompt grows by 4-6 lines. Path to the helper resolves via
`$STELLAR_ENGINE_HOME` env var (operator sets once); falls back to the
hard-coded `IdeaProjects/stellar-engine` location for the dev box.

### 5. Failure handling

- No `plane:<seq>` label on grava issue → exit 0 silently. Manually-created
  grava issues never reach Plane.
- No creds → exit 1, log to stderr. Agent's `|| true` swallows; pipeline
  continues; reconciler (Option 3, later) can catch up.
- Plane 5xx → built-in retry from `plane_client._request`.
- `plane_state_map` missing → fall back to Plane state group.

### 6. Tests

- `tests/cli/test_sync_plane_status.py`:
  - status→Plane-state mapping table (every cell)
  - missing `plane:<seq>` label → exit 0 no-op
  - `--plane-state X` override skips computation
  - search resolves seq → uuid; PATCH payload shape
- `tests/test_plane_client.py`: `list_states` smoke + mocked response

## Operator setup checklist

Step-by-step instructions live in **[`grava-plane-sync-setup.md`](./grava-plane-sync-setup.md)**. Quick summary:

1. Ensure `~/.config/plane/config.json` (or env) carries the right workspace
   creds — the sync helper reuses `plane_client.load_credentials()` with the
   same precedence as the rest of the agent.
2. `export STELLAR_ENGINE_HOME=/path/to/stellar-engine` in shell profile
   (full instructions in the setup doc — zsh / bash / fish + verification).
3. Add `plane_state_map:` block to each `systems/<Name>/system.yaml`.
4. First time: run `sync_plane_status.py grava-XXXX --list-states` (new flag)
   to dump the Plane states so the operator can populate the map correctly.

## v0 → v0.1 → out-of-scope

**v0 (this plan covers):**
- Helper script + `list_states` client method
- `plane_state_map` config in system.yaml
- coder / reviewer / pr-creator integration (5 file edits in
  `/Users/trungnguyenhoang/IdeaProjects/grava/.claude/agents/` + 5 in
  `plugins/grava/agents/`)
- Tests + docs

**v0.1 (follow-up):**
- `grava close` → Plane "done" wired automatically via `/ship`
- Grava-side hook as a backup integration point
- Polling reconciler for drift / agents that crashed before syncing

**Out of scope (future):**
- Plane → Grava reflux (spec is the source of truth; reverse sync not
  needed)
- Comment mirroring (Plane comment ↔ grava comment)
- Assignee sync

## Risks

- **State map is per-workspace.** Hard to validate without seeing the
  workspace's state list. Mitigation: `--list-states` dump for operator
  setup.
- **Grava vs Plane state model don't perfectly align.** Plane has 5 groups
  + custom names; grava has open/in_progress/closed + labels. The map is
  the operator's source of truth — over-mapping is OK, under-mapping just
  leaves Plane stuck on an old state until next sync.
- **Path coupling.** Hard-coding the stellar-engine path in agent prompts
  breaks on other machines. `$STELLAR_ENGINE_HOME` env var fixes; document
  in agent README.
- **Duplicate agent files.** `plugins/grava/agents/` mirrors
  `.claude/agents/`. Need to keep them in sync, or pick one as canonical
  and symlink the other. (Existing problem, this plan doesn't solve.)
- **No `plane:<seq>` label on manually-created grava issues.** Silent no-op
  is correct — but operators may be surprised. Document in the helper's
  `--help`.
