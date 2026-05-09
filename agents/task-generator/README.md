# task-generator (Phase 2)

Sub-agent that converts one Plane spec page into a planned epic-story-task
hierarchy and (with explicit operator approval) creates the work items in
Plane.

**Phase 2 = Plane writes are live.** Phases 3 (Grava mirror) and 4
(reconciler / idempotency) land in subsequent sessions.

See `../../docs/task-generator-strategy-bullets.md` and
`../../docs/task-generator/` for the full design.

## Install

```bash
pip install -r agents/task-generator/requirements.txt
```

`markdownify` and `pyyaml` are not yet folded into the repo's `setup.sh`;
follow-up will add them. Run the `pip install` above as a one-time step.

## Configure

Reuse `~/.config/plane/config.json` from `setup.sh`. Then add a project entry
to `<repo-root>/repo-map.yaml` with `repo_name` (folder name only — must live
as a sibling of `stellar-engine/`) and `git_url` (clone source if the folder
isn't already present locally):

```yaml
projects:
  "abc123-...-...":
    repo_name: sportbuddies
    git_url: git@github.com:trungnguyenhoang/sportbuddies.git
    workspace_prefix: SPORT
```

If the sibling folder is missing on first run, the agent will clone `git_url`
for you. Pass `--no-clone` to disable auto-clone.

## Preview a spec page (always do this first)

```bash
python3 agents/task-generator/cli/run.py <project_id> <page_id> --dry-run \
    [--target-repo PATH] [--allow-duplicate-pages] [--no-clone] \
    [--run-id YYYYMMDD-HHMMSS]
```

Output: a master preview path under `<target_repo>/runs/preview/<run_id>/`
plus one `.epic-NN-*.preview.md` per epic. Hand-review the master + the per-
epic files before you decide to write.

## Promote a previewed plan to actual Plane writes

Re-use the same work dir from the preview run so the writer doesn't re-fetch:

```bash
python3 agents/task-generator/cli/write.py \
    --work-dir <repo>/runs/work/<run_id> \
    --target-repo <repo> \
    --run-id <run_id> \
    --yes
```

Or skip the two-step composition and let `run.py` chain into the writer:

```bash
python3 agents/task-generator/cli/run.py <project_id> <page_id> --yes
# Without --yes, run.py prompts for confirmation between preview and write.
```

Result: Plane has the full hierarchy. A `RunReport` JSON lands at
`<repo>/runs/reports/<run_id>.json`.

### `--on-failure` modes

- `prompt` (default) — on a Plane API error, ask `Rollback? [y/N/skip]`.
- `abort` — write a partial-state report and exit 5. Re-run to resume.
- `rollback` — delete created work items in reverse order; exit 6 if rollback
  succeeds, else 5.

## Resume after a partial failure

Re-run the **same** `cli/write.py` invocation. The writer reads
`<work_dir>/run_state.json` and skips any op already in
`completed_op_indices`, picking up at the failed index.

## Step-by-step CLI (useful for debugging)

```bash
REPO=$(python3 agents/task-generator/cli/resolve_repo.py <project_id>)
WORK=$(python3 agents/task-generator/cli/init_run.py --target-repo "$REPO")
python3 agents/task-generator/cli/fetch.py    <project_id> <page_id> --work-dir "$WORK"
python3 agents/task-generator/cli/preflight.py <project_id> <page_id> --work-dir "$WORK"
python3 agents/task-generator/cli/parse.py    --work-dir "$WORK"
python3 agents/task-generator/cli/render.py   --work-dir "$WORK" --target-repo "$REPO"
# review the preview, then:
python3 agents/task-generator/cli/write.py    --work-dir "$WORK" --target-repo "$REPO" --yes
```

Intermediate JSON lands at `<repo>/runs/work/<run_id>/{page,preflight,ir,run_state}.json`.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | success |
| 1 | configuration error (missing creds, unmapped project, missing page, missing work-dir files) |
| 2 | `--no-clone` and folder missing |
| 3 | duplicate pages detected (or clone failure in `resolve_repo.py`) |
| 4 | missing required Plane work-item type (epic/story/task) at write time |
| 5 | partial Plane write — checkpoint persisted; re-run to resume |
| 6 | rollback completed — Plane state restored |

## Troubleshoot

| Symptom | Cause | Fix |
| --- | --- | --- |
| `KeyError: <uuid> not in repo-map` | Project not mapped | Add YAML entry or pass `--target-repo` |
| `RepoMapError: Folder exists but is not a git repo` | Sibling folder is a stale non-git directory | Delete or move the folder, re-run (agent clones fresh) |
| `RepoMapError: Permission denied (publickey)` | Bad SSH key / missing PAT / wrong `git_url` | Fix git auth or correct `git_url`; re-run |
| `RepoMapError: missing locally; ... --no-clone` | Sibling folder absent and `--no-clone` passed | Drop `--no-clone`, pre-clone, or pass `--target-repo PATH` |
| `Cannot write — Plane work-item type(s) missing` | Plane project on free tier | Enable paid tier or create the type, then re-run |
| Duplicate-page exit (3) | Multiple Plane pages share the target's title | **Resolve in the Plane web UI** (delete/rename — REST API does not support page update/delete), or pass `--allow-duplicate-pages` to bypass |
| `write.py` exit 5 | One op failed mid-run | Inspect `<repo>/runs/reports/<run_id>.json`; re-run identical command to resume, or pass `--on-failure rollback` |
| `write.py` exit 6 | Rollback completed | Investigate `failure_detail` in the report before retrying |
| `ParseWarning(kind="multiple_h2")` in preview | Spec has > 1 H2 (multi-epic mode is on by default — each H2 becomes an epic; this warning is informational) | If unintended, split the spec |
| Re-run created duplicates in Plane | Phase 2 has no search-based idempotency | Phase 4 reconciler will fix; for now, delete duplicates in Plane UI |

## Phase status

- **Phase 1:** parser + read-only Plane client + planner + dry-run preview.
- **Phase 2 (current):** Plane writes (creates / comments / Related-line
  description updates), checkpoint-based resume, optional rollback.
- **Phase 3:** Grava mirror in the target repo.
- **Phase 4:** Reconciler (idempotency by search, field-by-field diffs, orphan
  detection, type_marker → priority/label mapping).
