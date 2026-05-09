# task-generator (Phase 1)

Sub-agent that converts one Plane spec page into a planned epic-story-task
hierarchy preview.

**Phase 1 = dry-run only.** Phases 2 (Plane writes), 3 (Grava mirror), and 4
(reconciler/idempotency) land in subsequent sessions.

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

## Run (single command)

```bash
python3 agents/task-generator/cli/run.py <project_id> <page_id> --dry-run \
    [--target-repo PATH] [--allow-duplicate-pages] [--no-clone]
```

Output: a preview path under `<target_repo>/runs/preview/`. The orchestrator
composes `resolve_repo` → `init_run` → `fetch` → `preflight` → `parse` →
`render` in one Python process.

## Run (step by step, useful for debugging)

```bash
REPO=$(python3 agents/task-generator/cli/resolve_repo.py <project_id>)
WORK=$(python3 agents/task-generator/cli/init_run.py --target-repo "$REPO")
python3 agents/task-generator/cli/fetch.py    <project_id> <page_id> --work-dir "$WORK"
python3 agents/task-generator/cli/preflight.py <project_id> <page_id> --work-dir "$WORK"
python3 agents/task-generator/cli/parse.py    --work-dir "$WORK"
python3 agents/task-generator/cli/render.py   --work-dir "$WORK" --target-repo "$REPO"
```

Intermediate JSON lands at `<repo>/runs/work/<run_id>/{page,preflight,ir}.json`.
`cat` them between steps to inspect what each stage produced. The exit codes
are documented in `AGENT.md`.

## Validate

Open the preview Markdown file. Confirm that the spec page's H2 → epic, H3 →
story, bullet → task structure is reflected correctly. Repeat against 2–3 spec
pages.

## Troubleshoot

| Symptom | Cause | Fix |
| --- | --- | --- |
| `KeyError: <uuid> not in repo-map` | Project not mapped | Add YAML entry or pass `--target-repo` |
| `RepoMapError: Folder exists but is not a git repo` | Sibling folder is a stale non-git directory | Delete or move the folder, re-run (agent clones fresh) |
| `RepoMapError: Permission denied (publickey)` (or similar git stderr) | Clone failed — bad SSH key, missing PAT, or wrong `git_url` | Fix git auth (or correct `git_url` in `repo-map.yaml`); re-run |
| `RepoMapError: missing locally; ... --no-clone` | Sibling folder absent and `--no-clone` passed | Drop `--no-clone`, or pre-clone the repo, or pass `--target-repo PATH` |
| `Required Plane work-item type(s) missing: epic` | Plane project on free tier | Enable paid tier or create the type |
| Duplicate-page exit (code 3) | Multiple Plane pages share the target's title | **Resolve in the Plane web UI** (delete/rename — REST API does not support page update/delete, so the agent cannot fix this for you), or pass `--allow-duplicate-pages` to bypass and proceed against the target page id |
| `NotImplementedError: ...Phase 2 deliverable` | Ran without `--dry-run` | Re-run with `--dry-run` (Phase 2 not yet implemented) |
| `ParseWarning(kind="multiple_h2")` in preview | Spec has > 1 H2 | Split spec into one page per epic |

## Phase status

- **Phase 1 (this PR):** parser + read-only Plane client + planner + dry-run
  preview. Writers stubbed.
- **Phase 2:** Plane writes (epic / stories / tasks / comments / Related-line
  updates).
- **Phase 3:** Grava mirror in the target repo.
- **Phase 4:** Reconciler (idempotency, field-by-field diffs, orphan
  detection).
