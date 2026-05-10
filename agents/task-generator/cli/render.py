#!/usr/bin/env python3
"""taskgen-render: build the RunPlan from cached preflight + IR; write the preview Markdown."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ir import EpicNode, ParseWarning, StoryNode, TaskNode  # noqa: E402
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
    ap = argparse.ArgumentParser(description="Render the planned hierarchy as a preview Markdown file.")
    ap.add_argument("--work-dir", type=Path, required=True)
    ap.add_argument("--target-repo", type=Path, required=True)
    args = ap.parse_args()

    ir_path = args.work_dir / "ir.json"
    pre_path = args.work_dir / "preflight.json"
    for p in (ir_path, pre_path):
        if not p.exists():
            print(f"missing required file: {p}", file=sys.stderr)
            return 1

    ir_blob = json.loads(ir_path.read_text(encoding="utf-8"))
    pre_blob = json.loads(pre_path.read_text(encoding="utf-8"))

    epics = [_ir_from_dict(e) for e in ir_blob.get("epics", [])]
    warnings = [
        ParseWarning(kind=w["kind"], detail=w["detail"])
        for w in ir_blob.get("warnings", [])
    ]
    type_map = pre_blob.get("type_uuids", {})
    label_map = pre_blob.get("label_uuids", {})
    duplicates = pre_blob.get("duplicates", []) if pre_blob.get("duplicates_bypassed") else []
    page_title = ir_blob.get("page_title", "") or pre_blob.get("target_title", "")

    run_id = args.work_dir.name

    rp = plan_from_cached(
        epics=epics,
        type_map=type_map,
        label_map=label_map,
        target_repo=args.target_repo,
        warnings=warnings,
        run_id=run_id,
        page_title=page_title,
        duplicates_bypassed=duplicates,
        spec_page_id=pre_blob.get("page_id", ""),
        existing_plane=pre_blob.get("existing_plane"),
    )

    print(str(rp.preview_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
