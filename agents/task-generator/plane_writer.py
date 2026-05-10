"""Plane writer (Phase 2): walks RunPlan.plane_ops against the Plane API.

Per-op behaviour:
  - CreateWorkItem: POST work-item, capture {id, sequence_id} in state.ref_to_uuid.
  - AddComment: resolve target_ref_key -> UUID, POST comment.
  - UpdateWorkItem: resolve target_ref_key -> UUID, PATCH (or GET+merge for the
    description_html_append shape the planner emits for related-refs).
  - CreateLabel: POST label.

State (RunState) is checkpointed to <state_path> after every successful op via
atomic write (tmp + rename). Re-running with the same state file resumes from
the next un-completed index.

On PlaneClientError, the executor records the failure, persists state, then
branches on `on_failure`:
  - "abort": write report, return.
  - "rollback": delete created work items in reverse order (tasks->stories->epic).
                Comments and labels are not rolled back (comments live on items
                that get deleted; labels are workspace-scoped).
  - "prompt": print summary and ask y/N.
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from ir import (
    AddComment,
    CreateLabel,
    CreateWorkItem,
    Op,
    RunPlan,
    RunReport,
    RunState,
    UpdateWorkItem,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write_state(state: RunState, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _write_report(report: RunReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")


def load_state(path: Path) -> RunState | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return RunState(**data)


def execute(
    plan: RunPlan,
    client,
    state: RunState,
    project_id: str,
    type_map: dict[str, str],
    *,
    state_path: Path,
    report_path: Path,
    on_failure: Literal["prompt", "rollback", "abort"] = "prompt",
    progress_every: int = 25,
    input_fn=input,
    label_map: dict[str, str] | None = None,
    diff=None,
) -> RunReport:
    report = RunReport(
        run_id=state.run_id,
        spec_page_id=state.page_id,
        started_at=state.started_at,
    )
    completed = set(state.completed_op_indices)
    create_order: list[tuple[int, str, str]] = []  # (idx, ref_key, uuid) for rollback

    # Pre-populate create_order from any prior creates already in state.
    for idx in sorted(completed):
        op = plan.plane_ops[idx]
        if isinstance(op, CreateWorkItem) and op.ref_key in state.ref_to_uuid:
            create_order.append((idx, op.ref_key, state.ref_to_uuid[op.ref_key]))

    try:
        for idx, op in enumerate(plan.plane_ops):
            if idx in completed:
                continue
            _dispatch(
                op, idx, client, project_id, type_map, state, report,
                create_order, label_map or {}, diff,
            )
            completed.add(idx)
            state.completed_op_indices = sorted(completed)
            _atomic_write_state(state, state_path)
            if progress_every and (len(completed) % progress_every == 0):
                print(
                    f"[plane_writer] {len(completed)}/{state.ops_total} ops done",
                    file=sys.stderr,
                )
    except Exception as exc:  # noqa: BLE001 — capture *all* failures here
        return _handle_failure(
            exc, plan, client, project_id, state, report,
            create_order, state_path, report_path, on_failure, input_fn,
        )

    state.failed_op_index = None
    state.failure_detail = None
    _atomic_write_state(state, state_path)
    report.finished_at = _now_iso()
    _write_report(report, report_path)
    return report


def _dispatch(
    op: Op,
    idx: int,
    client,
    project_id: str,
    type_map: dict[str, str],
    state: RunState,
    report: RunReport,
    create_order: list[tuple[int, str, str]],
    label_map: dict[str, str],
    diff=None,
) -> None:
    if isinstance(op, CreateWorkItem):
        # Phase 4: consult the diff to decide create vs update vs skip.
        verdict_entry = diff.by_ref_key.get(op.ref_key) if diff is not None else None
        if verdict_entry is not None and verdict_entry.verdict == "no_change":
            existing_uuid = verdict_entry.existing_uuid
            state.ref_to_uuid[op.ref_key] = existing_uuid
            if verdict_entry.existing_sequence_id is not None:
                state.ref_to_sequence_id[op.ref_key] = verdict_entry.existing_sequence_id
            report.plane_created.append({
                "op_index": idx,
                "ref_key": op.ref_key,
                "node_kind": op.node_kind,
                "uuid": existing_uuid,
                "sequence_id": verdict_entry.existing_sequence_id,
                "title": op.title,
                "verdict": "no_change",
            })
            return
        if verdict_entry is not None and verdict_entry.verdict == "update":
            existing_uuid = verdict_entry.existing_uuid
            patch = {}
            for f in verdict_entry.fields_changed:
                if f == "title":
                    patch["name"] = op.title
                elif f == "description_html":
                    patch["description_html"] = op.description_html
                elif f == "priority":
                    patch["priority"] = op.priority or "none"
            if patch:
                client.update_work_item(project_id, existing_uuid, patch)
            state.ref_to_uuid[op.ref_key] = existing_uuid
            if verdict_entry.existing_sequence_id is not None:
                state.ref_to_sequence_id[op.ref_key] = verdict_entry.existing_sequence_id
            report.plane_updated.append({
                "op_index": idx,
                "ref_key": op.ref_key,
                "target_uuid": existing_uuid,
                "fields": list(patch.keys()),
                "verdict": "update",
            })
            return

        # Default = create path (Phase 2 behaviour).
        type_id = type_map.get(op.type_id_key) or ""
        if not type_id:
            raise RuntimeError(
                f"Cannot create work item: Plane type {op.type_id_key!r} not found in project. "
                f"Create the type in Plane and re-run."
            )
        payload = {
            "name": op.title,
            "type_id": type_id,
        }
        if op.description_html:
            payload["description_html"] = op.description_html
        if op.parent_ref:
            parent_uuid = state.ref_to_uuid.get(op.parent_ref)
            if not parent_uuid:
                raise RuntimeError(
                    f"Op {idx} ({op.ref_key}): parent_ref {op.parent_ref!r} unresolved "
                    f"(parent not created yet)."
                )
            payload["parent"] = parent_uuid
        label_uuids = [label_map[k] for k in op.label_keys if k in label_map]
        if label_uuids:
            payload["labels"] = label_uuids
        if op.priority:
            payload["priority"] = op.priority
        resp = client.create_work_item(project_id, payload)
        new_id = resp.get("id")
        seq = resp.get("sequence_id")
        if not new_id:
            raise RuntimeError(f"Op {idx} create response missing 'id': {resp!r}")
        state.ref_to_uuid[op.ref_key] = new_id
        if seq is not None:
            state.ref_to_sequence_id[op.ref_key] = seq
        report.plane_created.append({
            "op_index": idx,
            "ref_key": op.ref_key,
            "node_kind": op.node_kind,
            "uuid": new_id,
            "sequence_id": seq,
            "title": op.title,
        })
        create_order.append((idx, op.ref_key, new_id))
        return

    if isinstance(op, AddComment):
        target_uuid = state.ref_to_uuid.get(op.target_ref_key)
        if not target_uuid:
            raise RuntimeError(
                f"Op {idx} (comment): target_ref_key {op.target_ref_key!r} unresolved."
            )
        resp = client.add_comment(project_id, target_uuid, op.comment_html)
        report.plane_comments.append({
            "op_index": idx,
            "target_ref_key": op.target_ref_key,
            "target_uuid": target_uuid,
            "comment_id": resp.get("id"),
        })
        return

    if isinstance(op, UpdateWorkItem):
        target_uuid = state.ref_to_uuid.get(op.target_ref_key)
        if not target_uuid:
            raise RuntimeError(
                f"Op {idx} (update): target_ref_key {op.target_ref_key!r} unresolved."
            )
        patch = dict(op.patch)
        append_html = patch.pop("description_html_append", None)
        if append_html:
            current = client.get_work_item(project_id, target_uuid)
            existing = current.get("description_html") or ""
            # Phase 4: idempotent — if the planned append text is already
            # present (sentinel-fenced block from a prior run), no-op.
            if append_html.strip() in existing:
                report.plane_updated.append({
                    "op_index": idx,
                    "target_ref_key": op.target_ref_key,
                    "target_uuid": target_uuid,
                    "fields": [],
                    "verdict": "no_change_related_already_present",
                })
                return
            patch["description_html"] = existing + append_html
        client.update_work_item(project_id, target_uuid, patch)
        report.plane_updated.append({
            "op_index": idx,
            "target_ref_key": op.target_ref_key,
            "target_uuid": target_uuid,
            "fields": list(patch.keys()),
        })
        return

    if isinstance(op, CreateLabel):
        client.create_label(project_id, op.name, op.color)
        return

    raise RuntimeError(f"Op {idx}: unknown op type {type(op).__name__}")


def _handle_failure(
    exc: Exception,
    plan: RunPlan,
    client,
    project_id: str,
    state: RunState,
    report: RunReport,
    create_order: list[tuple[int, str, str]],
    state_path: Path,
    report_path: Path,
    on_failure: str,
    input_fn,
) -> RunReport:
    failed_idx = next(
        (i for i in range(len(plan.plane_ops)) if i not in state.completed_op_indices),
        None,
    )
    state.failed_op_index = failed_idx
    state.failure_detail = str(exc)
    _atomic_write_state(state, state_path)

    report.failed_op = {
        "index": failed_idx,
        "detail": str(exc),
        "exc_type": type(exc).__name__,
    }
    print(
        f"[plane_writer] FAILED at op {failed_idx}: {exc}",
        file=sys.stderr,
    )

    decision = on_failure
    if on_failure == "prompt":
        n_creates = len(create_order)
        msg = (
            f"\nFailed at op {failed_idx}. {n_creates} work item(s) already created.\n"
            f"Rollback (delete in reverse)? [y/N/skip]: "
        )
        try:
            answer = input_fn(msg).strip().lower()
        except EOFError:
            answer = ""
        if answer == "y":
            decision = "rollback"
        elif answer == "skip":
            print(
                "[plane_writer] 'skip' is not yet implemented in prompt mode; aborting.",
                file=sys.stderr,
            )
            decision = "abort"
        else:
            decision = "abort"

    if decision == "rollback":
        _rollback(client, project_id, create_order, report)
        state.rolled_back = True
        _atomic_write_state(state, state_path)

    report.finished_at = _now_iso()
    _write_report(report, report_path)
    return report


def _rollback(
    client,
    project_id: str,
    create_order: list[tuple[int, str, str]],
    report: RunReport,
) -> None:
    deleted = 0
    failed_deletes = []
    for idx, ref_key, uuid in reversed(create_order):
        try:
            client.delete_work_item(project_id, uuid)
            deleted += 1
        except Exception as exc:  # noqa: BLE001
            failed_deletes.append({"ref_key": ref_key, "uuid": uuid, "detail": str(exc)})
            print(
                f"[plane_writer] rollback: delete failed for {ref_key} ({uuid}): {exc}",
                file=sys.stderr,
            )
    report.rolled_back = not failed_deletes
    if failed_deletes:
        if report.failed_op is None:
            report.failed_op = {}
        report.failed_op["rollback_failures"] = failed_deletes
    print(
        f"[plane_writer] rollback complete: deleted {deleted}/{len(create_order)} items",
        file=sys.stderr,
    )
