"""Tests for reconcile.build_diff."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ir import CreateWorkItem  # noqa: E402
from reconcile import build_diff  # noqa: E402


TYPE_MAP = {"epic": "t-epic", "story": "t-story", "task": "t-task"}


def _ops_simple():
    """1 epic, 1 story under epic, 1 task under story."""
    return [
        CreateWorkItem(
            node_kind="epic", title="Epic A", description_html="<p>e</p>",
            type_id_key="epic", parent_ref=None, ref_key="epic:0",
        ),
        CreateWorkItem(
            node_kind="story", title="Story A.0", description_html="<p>s</p>",
            type_id_key="story", parent_ref="epic:0", ref_key="story:0.0",
        ),
        CreateWorkItem(
            node_kind="task", title="Task A.0.0", description_html="<p>t</p>",
            type_id_key="task", parent_ref="story:0.0", ref_key="task:0.0.0",
        ),
    ]


def test_no_existing_all_create():
    diff = build_diff(_ops_simple(), existing_plane=[], type_map=TYPE_MAP)
    counts = diff.counts()
    assert counts == {"create": 3, "update": 0, "no_change": 0, "orphan": 0}
    assert all(e.verdict == "create" for e in diff.by_ref_key.values())


def test_full_match_all_no_change():
    """All three items exist verbatim → all no_change."""
    existing = [
        {"id": "uE", "name": "Epic A", "type_id": "t-epic", "parent": None,
         "priority": "none", "sequence_id": 1, "description_html": "<p>e</p>", "labels": []},
        {"id": "uS", "name": "Story A.0", "type_id": "t-story", "parent": "uE",
         "priority": "none", "sequence_id": 2, "description_html": "<p>s</p>", "labels": []},
        {"id": "uT", "name": "Task A.0.0", "type_id": "t-task", "parent": "uS",
         "priority": "none", "sequence_id": 3, "description_html": "<p>t</p>", "labels": []},
    ]
    diff = build_diff(_ops_simple(), existing_plane=existing, type_map=TYPE_MAP)
    counts = diff.counts()
    assert counts == {"create": 0, "update": 0, "no_change": 3, "orphan": 0}
    epic_diff = diff.by_ref_key["epic:0"]
    assert epic_diff.existing_uuid == "uE"
    assert epic_diff.fields_changed == []


def test_title_drift_marks_update():
    existing = [
        {"id": "uE", "name": "Epic A — RENAMED", "type_id": "t-epic", "parent": None,
         "priority": "none", "sequence_id": 1, "description_html": "<p>e</p>", "labels": []},
    ]
    ops = _ops_simple()[:1]
    diff = build_diff(ops, existing_plane=existing, type_map=TYPE_MAP)
    # Different normalized title → no match → epic counts as create + orphan
    assert diff.by_ref_key["epic:0"].verdict == "create"
    assert len(diff.orphans) == 1
    assert diff.orphans[0].name == "Epic A — RENAMED"


def test_description_drift_marks_update():
    existing = [
        {"id": "uE", "name": "Epic A", "type_id": "t-epic", "parent": None,
         "priority": "none", "sequence_id": 1,
         "description_html": "<p>OUTDATED</p>", "labels": []},
    ]
    diff = build_diff(_ops_simple()[:1], existing_plane=existing, type_map=TYPE_MAP)
    epic_diff = diff.by_ref_key["epic:0"]
    assert epic_diff.verdict == "update"
    assert epic_diff.existing_uuid == "uE"
    assert "description_html" in epic_diff.fields_changed
    assert epic_diff.diff_detail["description_html"]["from"] == "<p>OUTDATED</p>"


def test_priority_drift_marks_update():
    existing = [
        {"id": "uE", "name": "Epic A", "type_id": "t-epic", "parent": None,
         "priority": "high", "sequence_id": 1,
         "description_html": "<p>e</p>", "labels": []},
    ]
    diff = build_diff(_ops_simple()[:1], existing_plane=existing, type_map=TYPE_MAP)
    epic_diff = diff.by_ref_key["epic:0"]
    assert epic_diff.verdict == "update"
    assert "priority" in epic_diff.fields_changed
    assert epic_diff.diff_detail["priority"]["from"] == "high"
    assert epic_diff.diff_detail["priority"]["to"] == "none"


def test_existing_not_in_plan_becomes_orphan():
    existing = [
        # the planned epic
        {"id": "uE", "name": "Epic A", "type_id": "t-epic", "parent": None,
         "priority": "none", "sequence_id": 1, "description_html": "<p>e</p>", "labels": []},
        # leftover that's not in spec
        {"id": "uOLD", "name": "Old removed thing", "type_id": "t-epic", "parent": None,
         "priority": "none", "sequence_id": 99, "description_html": "<p>x</p>", "labels": []},
    ]
    diff = build_diff(_ops_simple()[:1], existing_plane=existing, type_map=TYPE_MAP)
    assert diff.by_ref_key["epic:0"].verdict == "no_change"
    assert len(diff.orphans) == 1
    assert diff.orphans[0].uuid == "uOLD"


def test_related_block_in_existing_desc_does_not_trigger_update():
    """The planner appends a Related: footer in a separate UpdateWorkItem.
    The diff should ignore that block when comparing existing desc to planned.
    """
    existing_html = (
        "<p>e</p>\n\n<!-- task-generator:related -->\n"
        "Related: STELLAR-12, STELLAR-15\n"
        "<!-- /task-generator:related -->"
    )
    existing = [
        {"id": "uE", "name": "Epic A", "type_id": "t-epic", "parent": None,
         "priority": "none", "sequence_id": 1,
         "description_html": existing_html, "labels": []},
    ]
    diff = build_diff(_ops_simple()[:1], existing_plane=existing, type_map=TYPE_MAP)
    epic_diff = diff.by_ref_key["epic:0"]
    assert epic_diff.verdict == "no_change", (
        f"expected no_change, got {epic_diff.verdict} with fields {epic_diff.fields_changed}"
    )


def test_parent_resolution_chains_through_match():
    """A match on the epic gives us the epic's UUID; the story's join key
    must use that UUID as parent to find the existing story."""
    existing = [
        {"id": "uE", "name": "Epic A", "type_id": "t-epic", "parent": None,
         "priority": "none", "sequence_id": 1, "description_html": "<p>e</p>", "labels": []},
        {"id": "uS", "name": "Story A.0", "type_id": "t-story", "parent": "uE",
         "priority": "none", "sequence_id": 2, "description_html": "<p>s</p>", "labels": []},
    ]
    diff = build_diff(_ops_simple()[:2], existing_plane=existing, type_map=TYPE_MAP)
    assert diff.by_ref_key["story:0.0"].verdict == "no_change"
    assert diff.by_ref_key["story:0.0"].existing_uuid == "uS"
    assert diff.orphans == []


def test_normalized_title_matches_case_insensitive():
    existing = [
        {"id": "uE", "name": "  EPIC A  ", "type_id": "t-epic", "parent": None,
         "priority": "none", "sequence_id": 1, "description_html": "<p>e</p>", "labels": []},
    ]
    diff = build_diff(_ops_simple()[:1], existing_plane=existing, type_map=TYPE_MAP)
    assert diff.by_ref_key["epic:0"].verdict == "no_change"


def test_counts_method():
    existing = [
        {"id": "uE", "name": "Epic A", "type_id": "t-epic", "parent": None,
         "priority": "high", "sequence_id": 1, "description_html": "<p>e</p>", "labels": []},
        {"id": "orph", "name": "X", "type_id": "t-epic", "parent": None,
         "priority": "none", "sequence_id": 99, "description_html": "<p>x</p>", "labels": []},
    ]
    # Plan: 3 ops. Match epic only (with priority drift). Story+task → create.
    diff = build_diff(_ops_simple(), existing_plane=existing, type_map=TYPE_MAP)
    counts = diff.counts()
    assert counts["update"] == 1
    assert counts["create"] == 2
    assert counts["no_change"] == 0
    assert counts["orphan"] == 1
