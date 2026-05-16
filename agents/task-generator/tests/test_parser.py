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


def test_orphan_h3_synthesizes_implicit_epic():
    """H3 before any H2 used to drop as orphan; now lands under an implicit
    epic synthesized from the page H1."""
    epics, warnings = parse(_load("02_orphan_h3.md"), "https://x", "abc")
    kinds = [w.kind for w in warnings]
    assert "no_h2" in kinds
    assert "orphan_story" not in kinds
    assert len(epics) == 1
    epic = epics[0]
    assert epic.title == "Page Title"
    assert len(epic.stories) == 1
    story = epic.stories[0]
    assert story.title == "Orphan Story"
    assert [t.title for t in story.tasks] == ["task one", "task two"]


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


def test_h4_buckets_route_into_typed_story_fields():
    """H4 subsections under a story route bullets into typed buckets:
    'Acceptance Criteria' → story.acceptance_criteria; 'UI/UX Design'
    → story.design_links; bullets *before* any H4 → TaskNode. Unknown
    H4 names emit a warning and fold bullets into description."""
    epics, warnings = parse(_load("10_h4_tasks.md"), "https://x", "abc")
    assert len(epics) == 1
    epic = epics[0]
    assert epic.title == "Bravo Auth"
    assert len(epic.stories) == 2

    story1 = epic.stories[0]
    assert story1.title == "Build login endpoint"
    # Description carries the user-story narrative.
    assert "As a user, I want to log in" in story1.description_md

    # Pre-H4 bullets are tasks.
    task_titles = [t.title for t in story1.tasks]
    assert task_titles == [
        "Implement password hashing",
        "Wire login form",
        "Issue session token",
    ]
    # Acceptance Criteria bullets land in the typed field — NOT as tasks.
    assert story1.acceptance_criteria == [
        "Failed login shows a generic error",
        "Session persists across browser close",
        "Password is bcrypt-hashed before storage",
    ]
    # UI/UX Design bullets become DesignLinks.
    assert len(story1.design_links) == 3
    assert story1.design_links[0].label == "Figma — Login flow"
    assert story1.design_links[0].url == "https://figma.com/file/login"
    # Bare path → label=None.
    assert story1.design_links[1].label is None
    assert story1.design_links[1].url == "design/login-mockup.png"
    # Plain text → label=None, url=text.
    assert story1.design_links[2].label is None
    assert "brand-primary CTA" in story1.design_links[2].url

    # Story 2 has tasks + an unknown H4 ('Notes') that emits a warning.
    story2 = epic.stories[1]
    assert story2.title == "Build logout endpoint"
    assert [t.title for t in story2.tasks] == ["bullet task one", "bullet task two"]
    # Bullets under the 'Notes' H4 must NOT become tasks.
    assert "arbitrary content" not in [t.title for t in story2.tasks]
    assert any(w.kind == "unknown_section" and "Notes" in w.detail for w in warnings)


def test_h4_bucket_case_insensitive():
    """Bucket recognition tolerates case + trailing-colon variants."""
    md = (
        "# Title\n"
        "## Epic\n"
        "### Story\n\n"
        "- a task\n\n"
        "#### acceptance criteria:\n"
        "- AC one\n\n"
        "#### design\n"
        "- design note\n"
    )
    epics, _ = parse(md, "https://x", "abc")
    s = epics[0].stories[0]
    assert [t.title for t in s.tasks] == ["a task"]
    assert s.acceptance_criteria == ["AC one"]
    assert len(s.design_links) == 1


def test_new_h2_or_h3_ends_active_h4_bucket():
    """A new H2 or H3 must reset the H4 bucket — bullets after the next
    H3 become tasks again, not criteria from the previous story."""
    md = (
        "# T\n"
        "## E\n"
        "### S1\n\n"
        "#### Acceptance Criteria\n"
        "- AC for S1\n\n"
        "### S2\n"
        "- task for S2\n"
    )
    epics, _ = parse(md, "https://x", "abc")
    s1, s2 = epics[0].stories
    assert s1.acceptance_criteria == ["AC for S1"]
    assert s1.tasks == []
    assert [t.title for t in s2.tasks] == ["task for S2"]
    assert s2.acceptance_criteria == []


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
