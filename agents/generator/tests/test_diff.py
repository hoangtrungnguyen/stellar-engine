"""Tests for `agents/generator/diff.py` (Phase E3 helper)."""

from __future__ import annotations

from generator.diff import diff_outlines, render_diff_text
from generator.ir import Epic, Outline, Story, Task


def _outline(*epics: Epic) -> Outline:
    return Outline(epics=list(epics), confidence=0.5)


def _epic(title: str, *stories: Story) -> Epic:
    return Epic(title=title, stories=list(stories))


def _story(title: str, *, depends_on=None, ac=None, tasks=None) -> Story:
    return Story(
        title=title,
        depends_on=list(depends_on or []),
        acceptance_criteria=list(ac or []),
        tasks=[Task(title=t) for t in (tasks or [])],
    )


# ── happy paths ───────────────────────────────────────────────────────────────


def test_no_changes_is_empty():
    prev = _outline(_epic("A"), _epic("B"))
    curr = _outline(_epic("A"), _epic("B"))
    d = diff_outlines(prev, curr)
    assert d.is_empty()
    assert render_diff_text(d) == "No changes vs previous run."


def test_epic_added():
    prev = _outline(_epic("A"))
    curr = _outline(_epic("A"), _epic("B"))
    d = diff_outlines(prev, curr)
    assert d.epics_added == ["B"]
    assert d.epics_removed == []
    assert d.epics_renamed == []


def test_epic_removed():
    prev = _outline(_epic("A"), _epic("B"))
    curr = _outline(_epic("A"))
    d = diff_outlines(prev, curr)
    assert d.epics_removed == ["B"]
    assert d.epics_added == []


def test_epic_renamed_when_titles_similar():
    prev = _outline(_epic("Court Booking"))
    curr = _outline(_epic("Court Bookings"))   # one letter
    d = diff_outlines(prev, curr)
    assert len(d.epics_renamed) == 1
    assert d.epics_renamed[0].before == "Court Booking"
    assert d.epics_renamed[0].after == "Court Bookings"
    assert d.epics_added == []
    assert d.epics_removed == []


def test_distinct_titles_not_treated_as_rename():
    prev = _outline(_epic("Court Booking"))
    curr = _outline(_epic("Refund Policy"))
    d = diff_outlines(prev, curr)
    assert d.epics_added == ["Refund Policy"]
    assert d.epics_removed == ["Court Booking"]
    assert d.epics_renamed == []


# ── story + task drill-down ───────────────────────────────────────────────────


def test_story_added_in_existing_epic():
    prev = _outline(_epic("E", _story("S1")))
    curr = _outline(_epic("E", _story("S1"), _story("S2")))
    d = diff_outlines(prev, curr)
    assert len(d.story_diffs) == 1
    sd = d.story_diffs[0]
    assert sd.epic == "E"
    assert sd.added == ["S2"]
    assert sd.removed == []


def test_story_removed_in_existing_epic():
    prev = _outline(_epic("E", _story("S1"), _story("S2")))
    curr = _outline(_epic("E", _story("S1")))
    d = diff_outlines(prev, curr)
    sd = d.story_diffs[0]
    assert sd.removed == ["S2"]
    assert sd.added == []


def test_story_renamed_within_epic():
    prev = _outline(_epic("E", _story("US-01 Pick court")))
    curr = _outline(_epic("E", _story("US-01 — Pick a court")))
    d = diff_outlines(prev, curr)
    sd = d.story_diffs[0]
    assert len(sd.renamed) == 1
    assert sd.renamed[0].before.startswith("US-01")
    assert sd.added == []
    assert sd.removed == []


def test_task_added_and_removed():
    prev = _outline(_epic("E", _story("S1", tasks=["T1", "T2"])))
    curr = _outline(_epic("E", _story("S1", tasks=["T1", "T3"])))
    d = diff_outlines(prev, curr)
    sd = d.story_diffs[0]
    assert sd.tasks_added == ["T3"]
    assert sd.tasks_removed == ["T2"]


def test_story_diff_under_renamed_epic():
    prev = _outline(_epic("Court Booking", _story("S1")))
    curr = _outline(_epic("Court Bookings", _story("S1"), _story("S2")))
    d = diff_outlines(prev, curr)
    assert len(d.epics_renamed) == 1
    assert len(d.story_diffs) == 1
    assert d.story_diffs[0].epic == "Court Bookings"
    assert d.story_diffs[0].added == ["S2"]


# ── render_diff_text ──────────────────────────────────────────────────────────


def test_render_diff_text_includes_all_sections():
    prev = _outline(
        _epic("Booking", _story("S1", tasks=["T1"])),
        _epic("Gone"),
    )
    curr = _outline(
        _epic("Booking", _story("S1", tasks=["T2"]), _story("S2")),
        _epic("New"),
    )
    d = diff_outlines(prev, curr)
    text = render_diff_text(d)
    assert "Epics added" in text
    assert "+ New" in text
    assert "Epics removed" in text
    assert "- Gone" in text
    assert "Epic 'Booking':" in text
    assert "+ story: S2" in text
    assert "+ task:  T2" in text
    assert "- task:  T1" in text


def test_to_dict_is_jsonable():
    import json
    prev = _outline(_epic("A"))
    curr = _outline(_epic("A"), _epic("B"))
    d = diff_outlines(prev, curr)
    json.dumps(d.to_dict())   # must not raise
