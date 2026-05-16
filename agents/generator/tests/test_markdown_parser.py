"""Tests for the markdown → Section IR parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from generator.parser.markdown import parse_markdown, parse_text


_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample.md"


def test_root_is_synthetic_level_zero():
    root = parse_markdown(_FIXTURE)
    assert root.heading.level == 0
    assert root.heading.text == "sample"


def test_h1_becomes_first_child():
    root = parse_markdown(_FIXTURE)
    assert len(root.children) == 1
    h1 = root.children[0]
    assert h1.heading.level == 1
    assert h1.heading.text == "Court Booking Spec"
    assert h1.heading.anchor == "L1"


def test_h2_count():
    root = parse_markdown(_FIXTURE)
    h1 = root.children[0]
    h2s = [c for c in h1.children if c.heading.level == 2]
    assert [s.heading.text for s in h2s] == ["Epic 1: Court Booking", "Epic 2: Cancellations"]


def test_h3_under_h2():
    root = parse_markdown(_FIXTURE)
    epic1 = root.children[0].children[0]
    stories = [c.heading.text for c in epic1.children]
    assert stories == ["US-01 — Pick a court", "US-02 — Reserve a court"]


def test_paragraph_under_h1():
    root = parse_markdown(_FIXTURE)
    h1 = root.children[0]
    paras = [b for b in h1.blocks if b.kind == "paragraph"]
    assert len(paras) == 1
    assert "Intro paragraph" in paras[0].text


def test_ui_ux_list_block_captured():
    root = parse_markdown(_FIXTURE)
    epic1 = root.children[0].children[0]
    lists = [b for b in epic1.blocks if b.kind == "list"]
    assert lists, "expected list block under Epic 1 (the UI/UX Design list)"
    assert "Figma" in lists[0].text


def test_acceptance_criteria_list_under_story():
    root = parse_markdown(_FIXTURE)
    us01 = root.children[0].children[0].children[0]
    lists = [b for b in us01.blocks if b.kind == "list"]
    assert lists
    assert "Map shows pins" in lists[0].text


def test_code_block_captured():
    root = parse_markdown(_FIXTURE)
    us01 = root.children[0].children[0].children[0]
    code_blocks = [b for b in us01.blocks if b.kind == "code"]
    assert len(code_blocks) == 1
    assert "def render_map" in code_blocks[0].text
    # Fence markers must be stripped from the body.
    assert "```" not in code_blocks[0].text


def test_table_block_captured():
    root = parse_markdown(_FIXTURE)
    us02 = root.children[0].children[0].children[1]
    tables = [b for b in us02.blocks if b.kind == "table"]
    assert len(tables) == 1
    assert "| Field | Type |" in tables[0].text
    assert "| start | datetime |" in tables[0].text


def test_anchors_are_line_numbers():
    root = parse_markdown(_FIXTURE)
    h1 = root.children[0]
    epic1 = h1.children[0]
    # Epic 1 heading is on line 5 in the fixture.
    assert epic1.heading.anchor == "L5"


def test_empty_input_produces_root_only():
    root = parse_text("", source_label="empty")
    assert root.heading.level == 0
    assert root.children == []
    assert root.blocks == []


def test_orphan_content_before_first_heading():
    root = parse_text("just a paragraph\nwith two lines\n", source_label="orphan")
    assert root.children == []
    assert len(root.blocks) == 1
    assert root.blocks[0].kind == "paragraph"
    assert "two lines" in root.blocks[0].text


def test_h4_nests_under_h3():
    md = "# Top\n\n## A\n\n### B\n\n#### C\n\ndetail\n"
    root = parse_text(md)
    h1 = root.children[0]
    h2 = h1.children[0]
    h3 = h2.children[0]
    assert h3.heading.text == "B"
    h4 = h3.children[0]
    assert h4.heading.level == 4
    assert h4.heading.text == "C"


@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_fenced_code_supports_both_fence_styles(fence):
    md = f"# T\n\n{fence}\ncode body\n{fence}\n"
    root = parse_text(md)
    h1 = root.children[0]
    codes = [b for b in h1.blocks if b.kind == "code"]
    assert len(codes) == 1
    assert codes[0].text == "code body"


def test_numbered_list_recognised_as_list():
    md = "# T\n\n1. first\n2. second\n"
    root = parse_text(md)
    h1 = root.children[0]
    lists = [b for b in h1.blocks if b.kind == "list"]
    assert len(lists) == 1
    assert "first" in lists[0].text and "second" in lists[0].text
