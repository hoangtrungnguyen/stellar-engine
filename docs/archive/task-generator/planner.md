# Planner & Reconciler

`planner.py` produces the `RunPlan` from the IR; `reconciler.py` rewrites the plan against existing Plane state on a re-run.

## Planner

```python
# planner.py
def plan(ir: EpicNode, project_id: str, client: PlaneClient) -> RunPlan
```

### Pre-flight ops (read-only, run inside `plan()` to fail fast)

1. `list_work_item_types(project_id)` → cache a `{type_name: type_uuid}` map. Required types: `epic`, `story`, `task`. Bail with a clear error if any are missing.
2. `list_labels(project_id)` → cache `{label_name: label_uuid}`. Queue `CreateLabel` ops for any missing labels referenced by IR (this includes the three Plane-side cross-link labels used in Phase 3).

### Plane write ops (in this exact order)

1. `CreateWorkItem(epic, type_id=type_map["epic"], parent=None)`
2. for each story: `CreateWorkItem(story, type_id=type_map["story"], parent=epic.uuid)`
3. for each task: `CreateWorkItem(task, type_id=type_map["task"], parent=story.uuid)`
4. for each section in `epic.open_questions` and `epic.risks`: `AddComment(epic, html=...)`
5. for each created issue with `related_refs`: `UpdateWorkItem(issue, description += "\n\nRelated: STELLAR-12, STELLAR-15")` — deferred until all sequence IDs are known so the description-text relations resolve correctly.

### Preview

Render the ordered ops as a Markdown tree to `<spec-slug>-<timestamp>.preview.md` in the target repo (or stellar-engine workspace). Return the path on the `RunPlan` for the runner to surface to the user.

## Reconciler (Phase 4)

```python
# reconciler.py
def reconcile(plan: RunPlan, client: PlaneClient) -> ReconciledPlan
```

Rewrites the planner's output against existing Plane state when the same spec page has been processed before:

- For each planned `CreateWorkItem`, search existing work items by the spec-page URL embedded in the description (uses `search_work_items` with a description-text filter; falls back to a label query if Plane's text search proves unreliable).
- If found → demote the op from `Create` to `Update` and produce a field-level diff.
- If a live item references the spec page but does not match any planned op → mark as `orphan`. Orphans are never auto-deleted; they go into the run report and the preview header.
- The reconciled plan replaces the original plan in `runner.py` before `plane_writer.execute()` runs.

## See Also

- [data-model.md](data-model.md) — `RunPlan` and `Op` shapes.
- [parser.md](parser.md) — produces the IR consumed here.
- [writers.md](writers.md) — executes the `RunPlan`.
