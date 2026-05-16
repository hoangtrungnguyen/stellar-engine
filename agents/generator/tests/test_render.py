"""Tests for `agents/generator/render.py` (Phase E1)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from generator.ir import outline_from_dict
from generator.render import (
    RenderMeta,
    render,
    render_epic,
    slugify,
)


_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample_outline.json"


def _load_outline():
    return outline_from_dict(json.loads(_FIXTURE.read_text()))


def _meta(today: date = date(2026, 5, 16)) -> RenderMeta:
    return RenderMeta(
        source="docs/spec.md",
        run_id="20260516T100000Z",
        confidence=0.78,
        model="manual-claude-code",
        model_version="n/a",
        today=today,
    )


# ── slugify ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("text,expected", [
    ("Court Booking", "court-booking"),
    ("US-01 — Pick a court", "us-01-pick-a-court"),
    ("  Spaces  &  Punct?? ", "spaces-punct"),
    ("", ""),
])
def test_slugify(text, expected):
    assert slugify(text) == expected


# ── render() ──────────────────────────────────────────────────────────────────


def test_render_emits_one_file_per_epic(tmp_path):
    out = render(_load_outline(), system_name="Demo", out_dir=tmp_path, meta=_meta())
    assert len(out) == 2
    assert {d.epic_title for d in out} == {"Court Booking", "Cancellations"}
    for d in out:
        assert d.path.exists()
        assert d.path.parent == tmp_path


def test_filename_format(tmp_path):
    out = render(_load_outline(), system_name="Demo", out_dir=tmp_path, meta=_meta())
    names = sorted(d.path.name for d in out)
    assert names == [
        "2026-05-16-cancellations.md",
        "2026-05-16-court-booking.md",
    ]


def test_creates_out_dir(tmp_path):
    target = tmp_path / "deep" / "nested" / "drafts"
    render(_load_outline(), system_name="Demo", out_dir=target, meta=_meta())
    assert target.exists()


# ── render_epic body ──────────────────────────────────────────────────────────


def test_frontmatter_keys_present():
    epic = _load_outline().epics[0]
    text = render_epic(epic, system_name="Demo", meta=_meta())
    assert text.startswith("---\n")
    for key in (
        "generator_source:",
        "generator_run_id:",
        "generator_confidence:",
        "generator_model:",
        "generator_model_version:",
    ):
        assert key in text


def test_h1_uses_system_name():
    epic = _load_outline().epics[0]
    text = render_epic(epic, system_name="SportBuddies", meta=_meta())
    assert "\n# SportBuddies\n" in text


def test_h2_uses_epic_title():
    epic = _load_outline().epics[0]
    text = render_epic(epic, system_name="Demo", meta=_meta())
    assert "\n## Court Booking\n" in text


def test_ui_ux_design_block_rendered_as_h4_under_story():
    epic = _load_outline().epics[0]
    text = render_epic(epic, system_name="Demo", meta=_meta())
    assert "#### UI/UX Design" in text
    assert "- [Figma — Booking flow](https://figma.com/file/XXX/booking)" in text
    # design_link with label=None renders as bare URL.
    assert "- design/booking-mockup.png" in text


def test_ui_ux_design_block_omitted_when_empty():
    """US-02 (in same epic) has empty design_links — no UI/UX H4 in its block."""
    epic = _load_outline().epics[0]
    text = render_epic(epic, system_name="Demo", meta=_meta())
    us02_start = text.index("### US-02")
    snippet = text[us02_start:]
    assert "#### UI/UX Design" not in snippet


def test_h3_per_story():
    epic = _load_outline().epics[0]
    text = render_epic(epic, system_name="Demo", meta=_meta())
    assert "### US-01 — Pick a court" in text
    assert "### US-02 — Reserve a court" in text


def test_depends_on_blockquote_present():
    epic = _load_outline().epics[0]
    text = render_epic(epic, system_name="Demo", meta=_meta())
    assert "> Depends on: auth" in text


def test_depends_on_blockquote_omitted_when_empty():
    epic = _load_outline().epics[0]
    text = render_epic(epic, system_name="Demo", meta=_meta())
    # US-02 has no depends_on — must not have a blockquote between H3 and the
    # next section.
    us02_start = text.index("### US-02")
    snippet = text[us02_start:us02_start + 200]
    assert "> Depends on:" not in snippet


def test_story_description_rendered():
    """Story.description_md sits between H3 (and optional `> Depends on:`)
    and the task list."""
    epic = _load_outline().epics[0]
    text = render_epic(epic, system_name="Demo", meta=_meta())
    assert "As a customer, I want to browse available courts" in text


def test_tasks_rendered_as_bullets_under_story():
    """Tasks render as plain bullets directly under the story (before any
    H4), not as H4 sub-headings."""
    epic = _load_outline().epics[0]
    text = render_epic(epic, system_name="Demo", meta=_meta())
    assert "- Render the map widget" in text
    assert "- Wire location services" in text
    # Must NOT be rendered as an H4 task heading (old format).
    assert "#### Render the map widget" not in text


def test_acceptance_criteria_block_as_h4():
    epic = _load_outline().epics[0]
    text = render_epic(epic, system_name="Demo", meta=_meta())
    assert "#### Acceptance Criteria" in text
    assert "- Map shows pins within 5 km of current location" in text
    assert "- Tapping a pin opens the court detail sheet" in text
    # Old bold-marker form must NOT be emitted.
    assert "**Acceptance Criteria:**" not in text


def test_acceptance_criteria_omitted_when_empty():
    """US-02 has acceptance_criteria=[] — no AC H4 in its block."""
    epic = _load_outline().epics[0]
    text = render_epic(epic, system_name="Demo", meta=_meta())
    us02_start = text.index("### US-02")
    snippet = text[us02_start:]
    assert "#### Acceptance Criteria" not in snippet


def test_section_order_within_story():
    """Within a single story block, expect order:
       H3 → (blockquote) → description → tasks → #### AC → #### UI/UX."""
    epic = _load_outline().epics[0]
    text = render_epic(epic, system_name="Demo", meta=_meta())
    us01 = text[text.index("### US-01"):text.index("### US-02")]
    pos_desc = us01.index("As a customer")
    pos_task = us01.index("- Render the map widget")
    pos_ac = us01.index("#### Acceptance Criteria")
    pos_design = us01.index("#### UI/UX Design")
    assert pos_desc < pos_task < pos_ac < pos_design
