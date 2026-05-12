#!/usr/bin/env python3
"""taskgen-write: execute the RunPlan against Plane (Phase 2)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import plane_writer  # noqa: E402
from ir import EpicNode, ParseWarning, RunState, StoryNode, TaskNode  # noqa: E402
from plane_client import PlaneClient, load_credentials  # noqa: E402
from planner import plan_from_cached  # noqa: E402


def _ir_from_dict(d: dict) -> EpicNode:
    epic = EpicNode(
        title=d.get("title", ""),
        description_md=d.get("description_md", ""),
        spec_page_url=d.get("spec_page_url", ""),
        spec_page_id=d.get("spec_page_id", ""),
        open_questions=list(d.get("open_questions", [])),
        risks=list(d.get("risks", [])),
        related_refs=list(d.get("related_refs", [])),
    )
    for s in d.get("stories", []):
        story = StoryNode(
            title=s.get("title", ""),
            description_md=s.get("description_md", ""),
            type_marker=s.get("type_marker"),
            related_refs=list(s.get("related_refs", [])),
        )
        for t in s.get("tasks", []):
            story.tasks.append(TaskNode(
                title=t.get("title", ""),
                description_md=t.get("description_md", ""),
                type_marker=t.get("type_marker"),
                related_refs=list(t.get("related_refs", [])),
            ))
        epic.stories.append(story)
    return epic


def main() -> int:
    ap = argparse.ArgumentParser(description="Execute the planned ops against Plane.")
    ap.add_argument("--work-dir", type=Path, required=True)
    ap.add_argument("--target-repo", type=Path, required=True)
    ap.add_argument("--run-id", default=None,
                    help="Defaults to the work-dir basename.")
    ap.add_argument("--on-failure", choices=["prompt", "rollback", "abort"], default="prompt")
    ap.add_argument("--yes", action="store_true",
                    help="Skip the pre-write confirmation prompt.")
    ap.add_argument(
        "--no-plane-relations", action="store_true",
        help="Skip Phase 6 — don't post Plane `blocking` relations even if "
             "dep_graph.json exists in the work dir.",
    )
    ap.add_argument("--client-factory", default=None, help=argparse.SUPPRESS)
    args = ap.parse_args()

    work_dir: Path = args.work_dir
    page_path = work_dir / "page.json"
    pre_path = work_dir / "preflight.json"
    ir_path = work_dir / "ir.json"
    for p in (page_path, pre_path, ir_path):
        if not p.exists():
            print(f"missing required file: {p}", file=sys.stderr)
            return 1

    page_blob = json.loads(page_path.read_text(encoding="utf-8"))
    pre_blob = json.loads(pre_path.read_text(encoding="utf-8"))
    ir_blob = json.loads(ir_path.read_text(encoding="utf-8"))

    project_id = page_blob.get("project_id") or pre_blob.get("project_id")
    page_id = page_blob.get("page_id") or pre_blob.get("page_id")
    if not project_id or not page_id:
        print("page.json/preflight.json missing project_id or page_id", file=sys.stderr)
        return 1

    type_map = pre_blob.get("type_uuids", {})
    missing = [k for k in ("epic", "story", "task") if not type_map.get(k)]
    if missing:
        print(
            f"Cannot write — Plane work-item type(s) missing: {', '.join(missing)}. "
            f"Create them in Plane first (preflight.json reflects the missing set).",
            file=sys.stderr,
        )
        return 4

    label_map = pre_blob.get("label_uuids", {})
    duplicates_bypassed = (
        pre_blob.get("duplicates", []) if pre_blob.get("duplicates_bypassed") else []
    )
    page_title = ir_blob.get("page_title", "") or pre_blob.get("target_title", "")
    epics = [_ir_from_dict(e) for e in ir_blob.get("epics", [])]
    warnings = [
        ParseWarning(kind=w["kind"], detail=w["detail"])
        for w in ir_blob.get("warnings", [])
    ]

    run_id = args.run_id or work_dir.name

    existing_plane = pre_blob.get("existing_plane") or []
    plan = plan_from_cached(
        epics=epics,
        type_map=type_map,
        label_map=label_map,
        target_repo=args.target_repo,
        warnings=warnings,
        run_id=run_id,
        page_title=page_title,
        duplicates_bypassed=duplicates_bypassed,
        spec_page_id=page_id,
        existing_plane=existing_plane,
    )

    from reconcile import build_diff
    diff = build_diff(
        plan_ops=plan.plane_ops,
        existing_plane=existing_plane,
        type_map=type_map,
    )

    state_path = work_dir / "run_state.json"
    existing_state = plane_writer.load_state(state_path)

    if existing_state is None:
        if not args.yes:
            n = len(plan.plane_ops)
            try:
                answer = input(
                    f"About to execute {n} Plane op(s) against project {project_id}. "
                    f"Proceed? [y/N] "
                ).strip().lower()
            except EOFError:
                answer = ""
            if answer != "y":
                print("Aborted (no writes performed).", file=sys.stderr)
                return 0
        state = RunState(
            run_id=run_id,
            project_id=project_id,
            page_id=page_id,
            started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ops_total=len(plan.plane_ops),
        )
    else:
        state = existing_state
        state.ops_total = len(plan.plane_ops)
        if state.completed_op_indices:
            print(
                f"[write] Resuming run {state.run_id}: "
                f"{len(state.completed_op_indices)}/{state.ops_total} ops already complete.",
                file=sys.stderr,
            )

    if args.client_factory:  # test hook
        from importlib import import_module
        mod_name, attr = args.client_factory.rsplit(".", 1)
        client = getattr(import_module(mod_name), attr)()
    else:
        try:
            token, host, workspace = load_credentials()
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            return 1
        client = PlaneClient(host=host, workspace=workspace, token=token)

    report_path = args.target_repo / "runs" / "reports" / f"{run_id}.json"

    # Phase 6: load dep_graph.json (written by cli/run.py's analyzer step) so
    # plane_writer can mirror analyzer edges into Plane `blocking` relations.
    dep_edges: list[dict] = []
    if not args.no_plane_relations:
        dep_path = work_dir / "dep_graph.json"
        if dep_path.exists():
            try:
                dep_blob = json.loads(dep_path.read_text(encoding="utf-8"))
                dep_edges = dep_blob.get("resolved_edges", []) or []
            except json.JSONDecodeError as e:
                print(
                    f"WARNING: could not parse dep_graph.json ({e}); "
                    f"skipping Plane relations.",
                    file=sys.stderr,
                )

    report = plane_writer.execute(
        plan, client, state, project_id, type_map,
        state_path=state_path,
        report_path=report_path,
        on_failure=args.on_failure,
        label_map=label_map,
        diff=diff,
        dep_edges=dep_edges,
    )

    print(f"report: {report_path}")
    print(
        f"summary: created={len(report.plane_created)} "
        f"comments={len(report.plane_comments)} "
        f"updated={len(report.plane_updated)} "
        f"relations_created={len(report.plane_relations_created)} "
        f"relations_skipped={len(report.plane_relations_skipped)} "
        f"failed={'yes' if report.failed_op else 'no'} "
        f"rolled_back={report.rolled_back}"
    )

    if report.failed_op and report.rolled_back:
        return 6
    if report.failed_op:
        return 5
    return 0


if __name__ == "__main__":
    sys.exit(main())
