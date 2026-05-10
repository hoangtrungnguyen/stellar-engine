# task-generator (Phase 4)

Sub-agent that converts one Plane spec page into a planned epic-story-task
hierarchy, writes it to Plane (with explicit operator approval), and mirrors
the same hierarchy to Grava in the target repo.

**Phase 4 (current):** safe re-runs. Preflight lists existing Plane items
via the per-page sentinel label `tg:src:<page_id>`, builds a diff, and the
preview shows reconciliation counts + per-item verdicts (`create | update
| no_change | orphan`). The writer honors verdicts — re-running against an
unchanged spec is a no-op. Orphans are flagged but never deleted.

`type_marker` (parsed prefixes like `P0:`, `Bug:`) now propagates: `P0/P1`
→ Plane priority urgent/high; `Bug` / `Spike` → Plane labels.

See `../../docs/task-generator-strategy-bullets.md` and
`../../docs/task-generator/` for the design.

## Install

```bash
pip install -r agents/task-generator/requirements.txt
```

`markdownify` and `pyyaml` are not yet folded into the repo's `setup.sh`;
follow-up will add them. Run the `pip install` above as a one-time step.

## Configure

1. Reuse `~/.config/plane/config.json` from `setup.sh`.
2. Add a project entry to **`systems/<Name>/system.yaml`** (preferred) so the
   per-system spec, agent config, and Plane wiring stay co-located:

   ```yaml
   # systems/SportBuddies/system.yaml
   projects:
     "8af0f117-1dd0-4bfe-8db8-ff131d865534":
       repo_name: sport-buddies-web
       git_url: https://github.com/hoangtrungnguyen/sport-buddies-web.git
       workspace_prefix: WEBINTRO
   ```

   The agent merges every `systems/*/system.yaml` on top of root
   `repo-map.yaml` at runtime; per-system entries win on conflict. Use the
   root file only for shared overrides or temporary mappings.

3. **For Phase 3 only:** initialise Grava inside the target repo (one-time):

   ```bash
   cd /Users/trungnguyenhoang/IdeaProjects/sport-buddies-web
   grava init
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
plus one `.epic-NN-*.preview.md` per epic. Hand-review before deciding to
write.

## Promote to Plane writes (Phase 2)

Re-use the same work dir from the preview run so the writer doesn't re-fetch:

```bash
python3 agents/task-generator/cli/write.py \
    --work-dir <repo>/runs/work/<run_id> \
    --target-repo <repo> \
    --run-id <run_id> \
    --yes
```

Result: Plane has the full hierarchy. A `RunReport` JSON lands at
`<repo>/runs/reports/<run_id>.json`.

## Mirror to Grava (Phase 3)

After Phase 2 succeeds, mirror the hierarchy into the target repo's Grava DB:

```bash
python3 agents/task-generator/cli/grava.py \
    --work-dir <repo>/runs/work/<run_id> \
    --target-repo <repo> \
    --run-id <run_id> \
    --yes
```

The writer:

1. Searches Grava for `plane:<seq>` labels — if found, **updates** the
   existing issue (title / description / priority); else **creates** a new
   issue.
2. Applies cross-link labels per level:
   - Epic: `plane:<seq>`
   - Story: `plane:<seq>` + `plane-epic:<eseq>`
   - Task: `plane:<seq>` + `plane-story:<sseq>` + `plane-epic:<eseq>`
3. Embeds Plane URLs in each Grava description (and the spec-page URL on
   tasks).
4. Posts `Mirrored to Grava: grava-XXXX` as a comment on each Plane work
   item (only on first creation; the update path skips comment-back).
5. Runs `grava commit -m "task-generator: mirror Plane page <page_id>"`.

The same `<repo>/runs/reports/<run_id>.json` from Phase 2 is **extended**
with `grava_created`, `grava_updated`, `grava_anomalies`, and
`grava_commit_hash`.

## Single-shot orchestrator

```bash
# Stops after preview
python3 agents/task-generator/cli/run.py <project_id> <page_id> --yes --dry-run

# Stops after Plane (skip Grava)
python3 agents/task-generator/cli/run.py <project_id> <page_id> --yes --no-grava

# Full pipeline: preview → Plane writes → Grava mirror
python3 agents/task-generator/cli/run.py <project_id> <page_id> --yes
```

Without `--yes`, `run.py` prompts for confirmation between preview and writes.

## Resume after a partial failure

Re-run the **same** invocation. The writer reads the relevant state file
(`run_state.json` for Plane, `grava_state.json` for Grava) and skips any
op already in `completed_op_indices`, picking up at the failed index.

## Re-running against the same Plane page

Both phases are idempotent in Phase 4:

- **Plane (Phase 2)** uses sentinel label `tg:src:<page_id>` (applied on
  every create). Re-runs detect existing items, diff against the spec, and
  skip / patch / create accordingly. Orphans flagged in the preview, never
  auto-deleted.
- **Grava (Phase 3)** uses `plane:<seq>` label search. Re-running propagates
  Plane state into Grava via update path.

Pre-Phase-4 Plane items (no sentinel label) appear as orphans on a re-run.
Tag them in Plane UI with the right `tg:src:<page_id>` label or accept the
fresh-create.

## `--on-failure` modes

- `prompt` (default) — on a failure, ask `Rollback? [y/N]`.
- `abort` — write a partial-state report and exit 5. Re-run to resume.
- `rollback` — Phase 2 deletes Plane work items in reverse order; Phase 3
  drops Grava issues in reverse order (`grava drop --force`, soft-delete).

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
# then mirror:
python3 agents/task-generator/cli/grava.py    --work-dir "$WORK" --target-repo "$REPO" --yes
```

Intermediate JSON lands at
`<repo>/runs/work/<run_id>/{page,preflight,ir,run_state,grava_state}.json`.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | success |
| 1 | configuration error (missing creds, unmapped project, missing files, Plane phase incomplete in Phase 3) |
| 2 | `--no-clone` and folder missing |
| 3 | duplicate pages detected (or clone failure in `resolve_repo.py`) |
| 4 | missing required Plane work-item type (Phase 2) **or** Grava not initialised (Phase 3) |
| 5 | partial write — checkpoint persisted; re-run to resume |
| 6 | rollback completed |

## Troubleshoot

| Symptom | Cause | Fix |
| --- | --- | --- |
| `KeyError: <uuid> not in repo-map` | Project not mapped | Add YAML entry or pass `--target-repo` |
| `RepoMapError: Folder exists but is not a git repo` | Sibling folder is a stale non-git directory | Delete or move the folder, re-run (agent clones fresh) |
| `RepoMapError: Permission denied (publickey)` | Bad SSH key / missing PAT / wrong `git_url` | Fix git auth or correct `git_url`; re-run |
| `RepoMapError: missing locally; ... --no-clone` | Sibling folder absent and `--no-clone` passed | Drop `--no-clone`, pre-clone, or pass `--target-repo PATH` |
| `Cannot write — Plane work-item type(s) missing` | Plane project on free tier or types deleted | Create the type(s) in Plane, then re-run |
| Duplicate-page exit (3) | Multiple Plane pages share the target's title | **Resolve in the Plane web UI** (REST API does not support page update/delete), or pass `--allow-duplicate-pages` |
| `write.py` exit 5 | One Plane op failed mid-run | Inspect `<repo>/runs/reports/<run_id>.json`; re-run identical command to resume, or pass `--on-failure rollback` |
| `Plane API 400 ... Invalid HTML passed` | Plane rejects empty `description_html=""` | Already handled — the writer omits the field when empty |
| `grava.py` exit 1 + "Plane writes incomplete" | Phase 2 left `failed_op_index` set | Re-run `cli/write.py` to resume Plane first; only then re-run grava |
| `grava.py` exit 4 + "Grava is not initialised" | No `.grava.yaml` in target repo | `cd <target_repo> && grava init`, then re-run grava |
| `grava.py` exit 5 | One Grava op failed mid-run | Inspect `<work_dir>/grava_state.json`; re-run to resume, or pass `--on-failure rollback` |
| `report.grava_anomalies` non-empty | Two+ Grava issues share a `plane:<seq>` label | Resolve in Grava (drop one or relabel); re-run |
| Re-run against same page in Phase 2 created duplicates | Phase 2 has no search-based idempotency | Phase 4 reconciler will fix. For now: don't re-run Phase 2 against an already-written page |

## Phase status

- **Phase 1:** parser + read-only Plane client + planner + dry-run preview.
- **Phase 2:** Plane writes (creates / comments / Related-line description
  updates), checkpoint-based resume, optional rollback.
- **Phase 3:** Grava mirror with three-level subtask nesting, cross-link
  labels, Plane-URL embedding, comment-back, and label-based reconciliation.
- **Phase 4 (current):** Plane-side reconciliation — sentinel label per
  spec page, preview-time diffs (`create / update / no_change / orphan`),
  writer honors verdicts, `type_marker → priority/label` mapping.
- **Phase 5+ (future):** bidirectional drift (Grava→Plane), orphan
  remediation flows, sub-page expansion when Plane ships the API.
