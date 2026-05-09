"""Unit tests for planner.py."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ir import (  # noqa: E402
    AddComment,
    CreateWorkItem,
    EpicNode,
    ParseWarning,
    StoryNode,
    TaskNode,
    UpdateWorkItem,
)
from planner import (  # noqa: E402
    DuplicatePageError,
    PlannerError,
    assert_required_types,
    build_label_map,
    build_type_map,
    find_duplicate_pages,
    plan,
    plan_from_cached,
)


TYPES = [
    {"id": "type-epic", "name": "Epic"},
    {"id": "type-story", "name": "Story"},
    {"id": "type-task", "name": "Task"},
]
LABELS = [
    {"id": "lbl-1", "name": "plane:STELLAR-1"},
]


class FakeClient:
    def __init__(self, pages, types=None, labels=None):
        self._pages = pages
        self._types = types if types is not None else TYPES
        self._labels = labels if labels is not None else LABELS

    def list_pages(self, project_id):
        return self._pages

    def list_work_item_types(self, project_id):
        return self._types

    def list_labels(self, project_id):
        return self._labels


def _ir_with_two_stories():
    return [EpicNode(
        title="User Auth Flow",
        description_md="Some prose.",
        spec_page_url="https://example/spec",
        spec_page_id="page-A",
        stories=[
            StoryNode(
                title="Login",
                description_md="",
                tasks=[
                    TaskNode(title="form", description_md=""),
                    TaskNode(title="api", description_md="", related_refs=["STELLAR-9"]),
                ],
            ),
            StoryNode(title="Logout", description_md=""),
        ],
        open_questions=["MFA?"],
        risks=["downtime"],
        related_refs=["STELLAR-12"],
    )]


def test_find_duplicate_pages_detects_normalized_match():
    pages = [
        {"id": "page-A", "name": "User Auth Flow", "access": 0},
        {"id": "page-B", "name": "  user auth flow  ", "access": 0},
        {"id": "page-C", "name": "Other", "access": 0},
    ]
    title, dups = find_duplicate_pages(pages, "page-A")
    assert title == "User Auth Flow"
    ids = [d["id"] for d in dups]
    assert "page-B" in ids
    assert "page-C" not in ids


def test_find_duplicate_pages_none():
    pages = [
        {"id": "page-A", "name": "Solo", "access": 0},
        {"id": "page-B", "name": "Other", "access": 1},
    ]
    _, dups = find_duplicate_pages(pages, "page-A")
    assert dups == []


def test_find_duplicate_pages_skips_non_live_access():
    pages = [
        {"id": "page-A", "name": "Spec", "access": 0},
        {"id": "page-B", "name": "spec", "access": 2},   # other mode
        {"id": "page-C", "name": "Spec", "access": None}, # missing access
        {"id": "page-D", "name": "spec", "access": 1},   # private — counts
    ]
    title, dups = find_duplicate_pages(pages, "page-A")
    assert title == "Spec"
    ids = [d["id"] for d in dups]
    assert ids == ["page-D"]


def test_find_duplicate_pages_skips_archived_and_deleted():
    pages = [
        {"id": "page-A", "name": "Spec", "access": 0},
        {"id": "page-B", "name": "spec", "access": 0, "archived_at": "2026-05-09"},
        {"id": "page-C", "name": "spec", "access": 0, "deleted_at": "2026-05-09"},
        {"id": "page-D", "name": "spec", "access": 0},  # live dup — counts
    ]
    title, dups = find_duplicate_pages(pages, "page-A")
    ids = [d["id"] for d in dups]
    assert ids == ["page-D"]


def test_assert_required_types_passes():
    type_map = build_type_map(TYPES)
    assert_required_types(type_map)
    assert type_map["epic"] == "type-epic"


def test_assert_required_types_missing_raises():
    only_two = [{"id": "x", "name": "Story"}, {"id": "y", "name": "Task"}]
    with pytest.raises(PlannerError, match="epic"):
        assert_required_types(build_type_map(only_two))


def test_plan_duplicate_page_raises():
    pages = [
        {"id": "page-A", "name": "Title", "access": 0},
        {"id": "page-B", "name": "title", "access": 0},
    ]
    client = FakeClient(pages)
    ir = _ir_with_two_stories()
    with pytest.raises(DuplicatePageError):
        plan(ir, "proj", "page-A", client, Path("/tmp/x"), [], "ts")


def test_plan_duplicate_check_runs_before_type_lookup():
    pages = [
        {"id": "page-A", "name": "T", "access": 0},
        {"id": "page-B", "name": "t", "access": 0},
    ]
    bad_types = [{"id": "x", "name": "Story"}]
    client = FakeClient(pages, types=bad_types)
    with pytest.raises(DuplicatePageError):
        plan(_ir_with_two_stories(), "proj", "page-A", client, Path("/tmp/x"), [], "ts")


def test_plan_non_live_duplicates_do_not_block(tmp_path):
    pages = [
        {"id": "page-A", "name": "Solo", "access": 0},
        {"id": "page-B", "name": "solo", "access": 2},   # other mode
        {"id": "page-C", "name": "solo", "access": 0, "archived_at": "2026-05-09"},
        {"id": "page-D", "name": "solo", "access": 0, "deleted_at": "2026-05-09"},
    ]
    rp = plan(_ir_with_two_stories(), "proj", "page-A", FakeClient(pages),
              tmp_path, [], "20260509-160234", page_title="Solo")
    assert rp.preview_path.exists()


def test_plan_op_order(tmp_path):
    pages = [{"id": "page-A", "name": "Solo", "access": 0}]
    client = FakeClient(pages)
    ir = _ir_with_two_stories()
    rp = plan(ir, "proj", "page-A", client, tmp_path, [], "20260509-160234")

    op_kinds = [type(op).__name__ for op in rp.plane_ops]
    creates = [i for i, k in enumerate(op_kinds) if k == "CreateWorkItem"]
    comments = [i for i, k in enumerate(op_kinds) if k == "AddComment"]
    updates = [i for i, k in enumerate(op_kinds) if k == "UpdateWorkItem"]

    assert max(creates) < min(comments) < min(updates)
    assert op_kinds.count("CreateWorkItem") == 5
    assert op_kinds.count("AddComment") == 2
    assert op_kinds.count("UpdateWorkItem") == 2

    epic_op = rp.plane_ops[0]
    assert isinstance(epic_op, CreateWorkItem)
    assert epic_op.parent_ref is None
    assert epic_op.ref_key == "epic:0"

    story_ops = [op for op in rp.plane_ops if isinstance(op, CreateWorkItem) and op.node_kind == "story"]
    assert all(op.parent_ref == "epic:0" for op in story_ops)


def test_plan_multi_epic_disambiguates_ref_keys(tmp_path):
    epics = [
        EpicNode(title="E1", description_md="", spec_page_url="https://x", spec_page_id="p",
                 stories=[StoryNode(title="S0", description_md="",
                                    tasks=[TaskNode(title="t0", description_md="")])]),
        EpicNode(title="E2", description_md="", spec_page_url="https://x", spec_page_id="p",
                 stories=[StoryNode(title="S0", description_md="",
                                    tasks=[TaskNode(title="t0", description_md="")])]),
    ]
    rp = plan(epics, "proj", "page-A",
              FakeClient([{"id": "page-A", "name": "X", "access": 0}]),
              tmp_path, [], "20260509-160234")
    create_ops = [op for op in rp.plane_ops if isinstance(op, CreateWorkItem)]
    refs = [op.ref_key for op in create_ops]
    assert "epic:0" in refs and "epic:1" in refs
    assert "story:0.0" in refs and "story:1.0" in refs
    assert "task:0.0.0" in refs and "task:1.0.0" in refs


def test_plan_related_refs_update_only_when_non_empty(tmp_path):
    epics = [EpicNode(
        title="E",
        description_md="",
        spec_page_url="https://x",
        spec_page_id="page-A",
        stories=[
            StoryNode(title="S1", description_md="", tasks=[TaskNode(title="t1", description_md="")]),
            StoryNode(title="S2", description_md="", tasks=[
                TaskNode(title="with-ref", description_md="", related_refs=["STELLAR-12"]),
            ]),
        ],
    )]
    pages = [{"id": "page-A", "name": "X", "access": 0}]
    rp = plan(epics, "proj", "page-A", FakeClient(pages), tmp_path, [], "20260509-160234")
    update_ops = [op for op in rp.plane_ops if isinstance(op, UpdateWorkItem)]
    assert len(update_ops) == 1
    assert update_ops[0].target_ref_key == "task:0.1.0"


def test_preview_file_written(tmp_path):
    ir = _ir_with_two_stories()
    pages = [{"id": "page-A", "name": "Solo", "access": 0}]
    rp = plan(ir, "proj", "page-A", FakeClient(pages), tmp_path, [
        ParseWarning(kind="orphan_story", detail="some warning"),
    ], "20260509-160234", page_title="Solo")
    assert rp.preview_path.exists()
    text = rp.preview_path.read_text()
    assert "Solo" in text or "User Auth Flow" in text
    assert "## Warnings" in text
    assert "orphan_story" in text
    # Per-epic file also exists
    epic_files = list(rp.preview_path.parent.glob("*.epic-*.preview.md"))
    assert len(epic_files) == 1


def test_preview_shows_bypassed_duplicates(tmp_path):
    ir = _ir_with_two_stories()
    rp = plan_from_cached(
        epics=ir,
        type_map=build_type_map(TYPES),
        label_map=build_label_map(LABELS),
        target_repo=tmp_path,
        warnings=[],
        run_id="20260509-160234",
        page_title="Page",
        duplicates_bypassed=[{"id": "page-B", "name": "duplicate"}],
    )
    text = rp.preview_path.read_text()
    assert "Bypassed duplicate pages" in text
    assert "page-B" in text


def test_plan_allow_duplicate_pages_proceeds(tmp_path):
    pages = [
        {"id": "page-A", "name": "Title", "access": 0},
        {"id": "page-B", "name": "title", "access": 0},
    ]
    rp = plan(
        _ir_with_two_stories(),
        "proj",
        "page-A",
        FakeClient(pages),
        tmp_path,
        [],
        "20260509-160234",
        allow_duplicate_pages=True,
    )
    assert rp.preview_path.exists()
    text = rp.preview_path.read_text()
    assert "Bypassed duplicate pages" in text
