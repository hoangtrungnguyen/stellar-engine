"""Smoke test for ir.py dataclass construction."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ir import (  # noqa: E402
    AddComment,
    CreateLabel,
    CreateWorkItem,
    EpicNode,
    ParseWarning,
    RunPlan,
    RunReport,
    StoryNode,
    TaskNode,
    UpdateWorkItem,
)


def test_dataclasses_construct():
    task = TaskNode(title="t", description_md="")
    story = StoryNode(title="s", description_md="", tasks=[task])
    epic = EpicNode(
        title="e",
        description_md="",
        spec_page_url="https://x",
        spec_page_id="abc",
        stories=[story],
    )
    assert epic.stories[0].tasks[0].title == "t"
    assert epic.open_questions == []
    assert task.related_refs == []

    warn = ParseWarning(kind="multiple_h2", detail="2 H2s")
    assert warn.kind == "multiple_h2"

    op = CreateWorkItem(
        node_kind="epic",
        title="e",
        description_html="",
        type_id_key="epic",
        parent_ref=None,
        ref_key="epic",
    )
    assert op.label_keys == []

    comment = AddComment(target_ref_key="epic", comment_html="<p>q</p>")
    assert comment.target_ref_key == "epic"

    update = UpdateWorkItem(target_ref_key="epic", patch={"description_html": "..."})
    assert update.patch["description_html"] == "..."

    label = CreateLabel(name="plane:STELLAR-1")
    assert label.color == "#888"

    plan = RunPlan(plane_ops=[op], grava_ops=[], preview_path=Path("/tmp/p.md"), warnings=[warn])
    assert len(plan.plane_ops) == 1
    assert plan.grava_ops == []

    report = RunReport(spec_page_id="abc")
    assert report.spec_page_id == "abc"
    assert report.plane_created == []
