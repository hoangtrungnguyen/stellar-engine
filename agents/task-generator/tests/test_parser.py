"""Unit tests for parser.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parser import _strip_fences, _strip_type_marker, parse  # noqa: E402

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def test_simple_epic():
    epics, warnings = parse(_load("01_simple_epic.md"), "https://x", "abc")
    assert warnings == []
    assert len(epics) == 1
    epic = epics[0]
    assert epic.title == "User Auth Flow"
    assert len(epic.stories) == 2
    assert epic.stories[0].title == "Login"
    assert [t.title for t in epic.stories[0].tasks] == [
        "Build login form",
        "Validate credentials",
        "Issue session token",
    ]
    assert epic.stories[1].title == "Logout"
    assert [t.title for t in epic.stories[1].tasks] == ["Clear session", "Redirect to home"]


def test_orphan_h3_warns():
    epics, warnings = parse(_load("02_orphan_h3.md"), "https://x", "abc")
    kinds = [w.kind for w in warnings]
    assert "orphan_story" in kinds
    assert "no_h2" in kinds
    orphan = next(w for w in warnings if w.kind == "orphan_story")
    assert "Orphan Story" in orphan.detail


def test_out_of_scope_skipped():
    epics, warnings = parse(_load("03_out_of_scope.md"), "https://x", "abc")
    assert len(epics) == 1
    epic = epics[0]
    assert epic.title == "User Auth Flow"
    titles = [s.title for s in epic.stories]
    assert "Forgotten password" not in titles
    all_task_titles = [t.title for s in epic.stories for t in s.tasks]
    assert "This should NOT appear" not in all_task_titles
    assert "Neither should this" not in all_task_titles


def test_open_questions_three_bullets():
    epics, warnings = parse(_load("04_open_questions.md"), "https://x", "abc")
    epic = epics[0]
    assert len(epic.open_questions) == 3
    assert epic.open_questions[0] == "Should we use OAuth or email/password?"
    assert len(epic.risks) == 2
    assert epic.risks[0] == "Auth provider downtime"


def test_cross_refs():
    epics, warnings = parse(_load("05_cross_refs.md"), "https://x", "abc", workspace_prefix="STELLAR")
    epic = epics[0]
    assert "STELLAR-12" in epic.related_refs
    story = epic.stories[0]
    assert "STELLAR-15" in story.related_refs
    assert "STELLAR-20" in story.related_refs
    task_refs = [ref for t in story.tasks for ref in t.related_refs]
    assert "STELLAR-12" in task_refs
    assert "STELLAR-15" in task_refs


def test_fenced_code_no_phantom_epic():
    epics, warnings = parse(_load("06_fenced_code_heading.md"), "https://x", "abc")
    assert len(epics) == 1
    epic = epics[0]
    titles = [s.title for s in epic.stories]
    assert epic.title == "Real Epic"
    assert "Fake story" not in titles
    assert "Real Story" in titles
    assert "Another Real Story" in titles
    all_tasks = [t.title for s in epic.stories for t in s.tasks]
    assert "fake task" not in all_tasks
    assert "## Fake epic" in epic.description_md


def test_inline_type_marker():
    epics, warnings = parse(_load("07_inline_type_marker.md"), "https://x", "abc")
    epic = epics[0]
    assert epic.title == "Payment Hangs"
    story = epic.stories[0]
    assert story.title == "investigate timeout"
    assert story.type_marker == "Spike"
    markers = {t.title: t.type_marker for t in story.tasks}
    assert markers["payment hangs on submit"] == "Bug"
    assert markers["rollback button missing"] == "P0"
    assert markers["confirmation email delayed"] == "P1"
    assert markers["normal task with no marker"] is None


def test_multiple_h2_produces_multiple_epics():
    epics, warnings = parse(_load("08_multiple_h2.md"), "https://x", "abc")
    assert len(epics) == 2
    assert epics[0].title == "First Epic"
    assert epics[1].title == "Second Epic (should warn and be skipped)"
    assert [s.title for s in epics[0].stories] == ["Story A"]
    assert [s.title for s in epics[1].stories] == ["Story B"]
    assert all(w.kind != "multiple_h2" for w in warnings)


def test_no_h2_warns():
    epics, warnings = parse(_load("09_no_h2.md"), "https://x", "abc")
    assert len(epics) == 1
    assert epics[0].title == "Standalone Page Title"
    assert epics[0].stories == []
    kinds = [w.kind for w in warnings]
    assert "no_h2" in kinds


def test_strip_type_marker_unit():
    assert _strip_type_marker("Bug: payment hangs") == ("payment hangs", "Bug")
    assert _strip_type_marker("Login flow") == ("Login flow", None)
    assert _strip_type_marker("P0: rollback") == ("rollback", "P0")


def test_strip_fences_unit():
    md = "## Real\n\n```\n## Fake\n```\n\n### Story\n"
    cleaned, blocks = _strip_fences(md)
    assert "## Fake" not in cleaned
    assert "## Real" in cleaned
    assert "### Story" in cleaned
    assert len(blocks) == 1
    assert "## Fake" in blocks[0]
