# Writers

Two writers execute the `RunPlan` against external systems: `plane_writer.py` for Phase 2 (Plane), `grava_writer.py` for Phase 3 (target repo).

## Plane Writer (Phase 2)

```python
# plane_writer.py
def execute(plan: RunPlan, client: PlaneClient, state: RunState) -> RunReport
```

Walks `plan.plane_ops` sequentially, recording each created UUID into `state` as the response comes back.

### Per-op behaviour

- **Success** → append to `state.plane_created` with `{type, uuid, sequence_id, title}`.
- **4xx / 5xx other than 429** → trip the failure path:
  1. Print the failed op + response body.
  2. Ask the user whether to roll back.
  3. If yes → delete in reverse order: tasks → stories → epic. Comments and label-create ops are not rolled back (comments live on the epic which gets deleted; labels are workspace-scoped and reusable).
  4. If no → exit with a partial-state report so the user can resolve manually.

### Idempotency path

Triggered by [reconciler](planner.md#reconciler-phase-4):

- For each existing matching item, compare the planned payload field-by-field against the live state.
- Drop ops where every field already matches.
- Convert ops to `UpdateWorkItem` where some fields differ, and surface the diff in the preview.
- Require explicit user `yes` in the chat before any patches are applied.

## Grava Writer (Phase 3)

Out of immediate scope for the Plane-side validation, but the structure is:

- Read `<target_repo>/CLAUDE.md` and any `<target_repo>/docs/cli.md` at runtime; never hardcode flag spelling.
- Create the epic with the repo's `create` command. Capture the returned Grava ID.
- For each story: `subtask` command under the epic.
- For each task: `subtask` command under the story. Grava supports unlimited nesting depth (`grava-abc.1.1` style IDs), so tasks live as true subtasks of stories.
- Apply three labels per Grava issue: `plane:<own_seq_id>`, `plane-story:<parent_story_seq_id>`, `plane-epic:<epic_seq_id>`.
- Comment the Grava ID back on each Plane work item.

## See Also

- [data-model.md](data-model.md) — `RunPlan`, `RunReport`, `Op` shapes.
- [planner.md](planner.md) — produces the `RunPlan` and rewrites it for re-runs.
- [plane-client.md](plane-client.md) — REST client used by `plane_writer`.
- [runner.md](runner.md) — invokes the writers in order.
