"""Tests for `agents/generator/mermaid.py` (epic-dep extractor).

The parser supports a small subset of Mermaid graph / flowchart syntax —
just enough to recognise `A --> B` edges with optional `[Label]`,
`(Label)`, `{Label}` shape wrappers. Direction tokens and arrow styles
are tolerated but ignored. Undirected edges (`A --- B`) and unrelated
graph constructs (subgraphs, classDef, click handlers) are skipped.
"""

from __future__ import annotations

import pytest

from generator.mermaid import extract_edges


# ── basic edges ───────────────────────────────────────────────────────────────


def test_basic_edges_with_bare_ids():
    text = "graph TD\nA --> B\nB --> C\n"
    assert extract_edges(text) == [("A", "B"), ("B", "C")]


def test_labeled_nodes_square_brackets():
    text = "graph TD\nA[Foo] --> B[Bar]\n"
    assert extract_edges(text) == [("Foo", "Bar")]


def test_labeled_nodes_parentheses():
    text = "graph LR\nA(Foo) --> B(Bar)\n"
    assert extract_edges(text) == [("Foo", "Bar")]


def test_labeled_nodes_braces():
    text = "graph LR\nA{Foo} --> B{Bar}\n"
    assert extract_edges(text) == [("Foo", "Bar")]


def test_mixed_labeled_and_bare():
    text = "graph TD\nA[Authentication] --> B\nB --> C[Cancellations]\n"
    assert extract_edges(text) == [
        ("Authentication", "B"),
        ("B", "Cancellations"),
    ]


def test_id_label_persists_across_edges():
    """Once `A[Label]` is declared, later bare references to `A` resolve
    to the registered label (Mermaid's node-vs-edge semantics)."""
    text = (
        "graph TD\n"
        "A[Authentication] --> B[Court Booking]\n"
        "B --> C[Cancellations]\n"
    )
    assert extract_edges(text) == [
        ("Authentication", "Court Booking"),
        ("Court Booking", "Cancellations"),
    ]


def test_label_can_be_set_on_either_side():
    """A label declared on the right of one edge propagates to a later
    bare reference on the left of a subsequent edge."""
    text = (
        "graph TD\n"
        "A --> B[Court Booking]\n"
        "B --> C\n"
    )
    assert extract_edges(text) == [
        ("A", "Court Booking"),
        ("Court Booking", "C"),
    ]


# ── declaration variants ──────────────────────────────────────────────────────


def test_flowchart_keyword():
    text = "flowchart TD\nA --> B\n"
    assert extract_edges(text) == [("A", "B")]


def test_direction_ignored():
    """Direction tokens (TD, LR, BT, RL) are accepted but ignored — edges
    are always read left → right per arrow direction."""
    for dir_token in ("TD", "LR", "BT", "RL", "TB"):
        text = f"graph {dir_token}\nA --> B\n"
        assert extract_edges(text) == [("A", "B")], f"failed for {dir_token}"


# ── arrow style variants ──────────────────────────────────────────────────────


def test_dotted_arrow():
    assert extract_edges("graph TD\nA -.-> B\n") == [("A", "B")]


def test_thick_arrow():
    assert extract_edges("graph TD\nA ==> B\n") == [("A", "B")]


def test_arrow_with_label():
    """`A -->|label| B` strips the edge label."""
    assert extract_edges("graph TD\nA -->|sometimes| B\n") == [("A", "B")]


def test_arrow_no_space():
    assert extract_edges("graph TD\nA-->B\n") == [("A", "B")]


# ── filtering ────────────────────────────────────────────────────────────────


def test_comments_skipped():
    text = "graph TD\n%% this is a comment\nA --> B\n%% trailing\n"
    assert extract_edges(text) == [("A", "B")]


def test_undirected_edges_skipped():
    """`A --- B` has no direction → no dependency edge."""
    text = "graph TD\nA --- B\nC --> D\n"
    assert extract_edges(text) == [("C", "D")]


def test_blank_lines_ignored():
    text = "graph TD\n\nA --> B\n\n\nC --> D\n"
    assert extract_edges(text) == [("A", "B"), ("C", "D")]


def test_malformed_lines_skipped():
    """Lines that don't match the edge grammar are silently dropped."""
    text = "graph TD\nA --> B\nrandom garbage line\nC --> D\n"
    assert extract_edges(text) == [("A", "B"), ("C", "D")]


# ── empty / non-graph input ───────────────────────────────────────────────────


def test_empty_string_returns_empty():
    assert extract_edges("") == []


def test_no_graph_declaration_returns_empty():
    """A code block without a `graph` / `flowchart` header is not a
    dependency graph — return [] so the caller can ignore the block."""
    assert extract_edges("A --> B\nC --> D\n") == []


def test_non_graph_keyword_returns_empty():
    """`sequenceDiagram`, `stateDiagram`, etc. are not dependency graphs."""
    assert extract_edges("sequenceDiagram\nA->>B: hi\n") == []


# ── whitespace tolerance ──────────────────────────────────────────────────────


def test_leading_whitespace_in_body():
    text = "graph TD\n    A --> B\n  B --> C\n"
    assert extract_edges(text) == [("A", "B"), ("B", "C")]


def test_trailing_whitespace_in_label():
    """`A[ Court Booking ]` → label is trimmed."""
    text = "graph TD\nA[ Court Booking ] --> B[Cancellations]\n"
    assert extract_edges(text) == [("Court Booking", "Cancellations")]


# ── parametric label-shape coverage ───────────────────────────────────────────


@pytest.mark.parametrize("lhs,rhs", [
    ("A[Foo]", "B[Bar]"),
    ("A(Foo)", "B(Bar)"),
    ("A{Foo}", "B{Bar}"),
    ("A[\"Foo\"]", "B[\"Bar\"]"),
])
def test_label_shape_variants(lhs, rhs):
    text = f"graph TD\n{lhs} --> {rhs}\n"
    edges = extract_edges(text)
    assert edges == [("Foo", "Bar")], f"failed for {lhs} --> {rhs}"
