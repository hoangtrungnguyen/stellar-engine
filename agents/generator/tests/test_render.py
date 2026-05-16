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


def test_ui_ux_design_block_rendered():
    epic = _load_outline().epics[0]
    text = render_epic(epic, system_name="Demo", meta=_meta())
    assert "**UI/UX Design:**" in text
    assert "[Figma — Booking flow](https://figma.com/x)" in text
    # design_link with label=None renders as bare URL.
    assert "- design/booking-mockup.png" in text


def test_ui_ux_design_block_omitted_when_empty():
    epic = _load_outline().epics[1]  # Cancellations: empty design_links
    text = render_epic(epic, system_name="Demo", meta=_meta())
    assert "**UI/UX Design:**" not in text


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


def test_acceptance_criteria_block():
    epic = _load_outline().epics[0]
    text = render_epic(epic, system_name="Demo", meta=_meta())
    assert "**Acceptance Criteria:**" in text
    assert "- Map shows pins within 5 km" in text
    assert "- Pin tap opens detail sheet" in text


def test_h4_task_with_ac():
    epic = _load_outline().epics[0]
    text = render_epic(epic, system_name="Demo", meta=_meta())
    assert "#### Render map" in text
    assert "- use Goong tiles" in text
