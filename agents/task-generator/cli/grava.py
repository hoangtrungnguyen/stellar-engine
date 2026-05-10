#!/usr/bin/env python3
"""taskgen-grava: mirror the Plane hierarchy into Grava (Phase 3)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import grava_writer  # noqa: E402
from ir import (  # noqa: E402
    EpicNode,
    GravaState,
    ParseWarning,
    RunState,
    StoryNode,
    TaskNode,
)
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
    ap = argparse.ArgumentParser(description="Mirror the Plane hierarchy into Grava (Phase 3).")
    ap.add_argument("--work-dir", type=Path, required=True)
    ap.add_argument("--target-repo", type=Path, required=True)
    ap.add_argument("--run-id", default=None,
                    help="Defaults to the work-dir basename.")
    ap.add_argument("--on-failure", choices=["prompt", "rollback", "abort"], default="prompt")
    ap.add_argument("--yes", action="store_true",
                    help="Skip the pre-mirror confirmation prompt.")
    ap.add_argument("--actor", default="task-generator",
                    help="GRAVA_ACTOR value passed to grava subcommands.")
    ap.add_argument("--client-factory", default=None, help=argparse.SUPPRESS)
    args = ap.parse_args()

    work_dir: Path = args.work_dir
    page_path = work_dir / "page.json"
    pre_path = work_dir / "preflight.json"
    ir_path = work_dir / "ir.json"
    plane_state_path = work_dir / "run_state.json"
    for p in (page_path, pre_path, ir_path, plane_state_path):
        if not p.exists():
            print(f"missing required file: {p}", file=sys.stderr)
            return 1

    page_blob = json.loads(page_path.read_text(encoding="utf-8"))
    pre_blob = json.loads(pre_path.read_text(encoding="utf-8"))
    ir_blob = json.loads(ir_path.read_text(encoding="utf-8"))
    plane_state = RunState(**json.loads(plane_state_path.read_text(encoding="utf-8")))

    if plane_state.failed_op_index is not None:
        print(
            f"Plane writes incomplete (failed_op_index={plane_state.failed_op_index}). "
            f"Resolve Phase 2 first (re-run cli/write.py to resume, or roll back).",
            file=sys.stderr,
        )
        return 1

    if not (args.target_repo / ".grava.yaml").exists():
        print(
            f"Grava is not initialised in {args.target_repo}. "
            f"Run 'cd {args.target_repo} && grava init', then re-run.",
            file=sys.stderr,
        )
        return 4

    project_id = page_blob.get("project_id")
    page_id = page_blob.get("page_id")
    spec_page_url = page_blob.get("spec_page_url", "")
    type_map = pre_blob.get("type_uuids", {})
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
    )

    state_path = work_dir / "grava_state.json"
    existing_state = grava_writer.load_state(state_path)

    if existing_state is None:
        if not args.yes:
            n = sum(1 for op in plan.plane_ops if type(op).__name__ == "CreateWorkItem")
            try:
                answer = input(
                    f"About to mirror {n} Plane work item(s) to Grava in {args.target_repo}. "
                    f"Proceed? [y/N] "
                ).strip().lower()
            except EOFError:
                answer = ""
            if answer != "y":
                print("Aborted (no Grava writes performed).", file=sys.stderr)
                return 0
        state = GravaState(
            run_id=run_id,
            target_repo=str(args.target_repo),
            started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ops_total=len(plan.plane_ops),
        )
    else:
        state = existing_state
        state.ops_total = len(plan.plane_ops)
        if state.completed_op_indices:
            print(
                f"[grava] Resuming run {state.run_id}: "
                f"{len(state.completed_op_indices)}/{state.ops_total} ops already complete.",
                file=sys.stderr,
            )

    if args.client_factory:  # test hook
        from importlib import import_module
        mod_name, attr = args.client_factory.rsplit(".", 1)
        client = getattr(import_module(mod_name), attr)()
    else:
        try:
            token, host, workspace_creds = load_credentials()
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            return 1
        client = PlaneClient(host=host, workspace=workspace_creds, token=token)

    # Workspace for URL building. Prefer creds, fall back to spec_page_url parse.
    workspace = workspace_creds if not args.client_factory else "ws"

    report_path = args.target_repo / "runs" / "reports" / f"{run_id}.json"

    report = grava_writer.execute(
        plan, plane_state, args.target_repo, client, project_id,
        spec_page_url, workspace,
        state=state,
        state_path=state_path,
        report_path=report_path,
        on_failure=args.on_failure,
        actor=args.actor,
    )

    print(f"report: {report_path}")
    print(
        f"summary: grava_created={len(report.grava_created)} "
        f"grava_updated={len(report.grava_updated)} "
        f"anomalies={len(report.grava_anomalies)} "
        f"plane_comments={len(report.plane_comments)} "
        f"commit={report.grava_commit_hash or '(none)'} "
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
