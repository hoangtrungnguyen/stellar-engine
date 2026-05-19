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


# ── standalone node declarations (label-first authoring style) ────────────────


def test_standalone_node_declaration_registers_label():
    """A node declared on its own line (`A[Foo]` alone) registers the
    label so later bare references resolve to it."""
    text = (
        "graph TD\n"
        "A[Foo]\n"
        "B[Bar]\n"
        "A --> B\n"
    )
    assert extract_edges(text) == [("Foo", "Bar")]


def test_standalone_node_with_paren_label():
    text = "graph TD\nA(Foo)\nA --> B\n"
    assert extract_edges(text) == [("Foo", "B")]


def test_standalone_node_with_brace_label():
    text = "graph TD\nA{Foo}\nA --> B\n"
    assert extract_edges(text) == [("Foo", "B")]


def test_standalone_node_with_quoted_label():
    text = 'graph TD\nA["Foo"]\nA --> B\n'
    assert extract_edges(text) == [("Foo", "B")]


# ── HTML inside labels ────────────────────────────────────────────────────────


def test_html_tag_stripped_from_label():
    text = 'graph TD\nA["<b>Foo</b>"] --> B\n'
    assert extract_edges(text) == [("Foo", "B")]


def test_br_tag_becomes_space():
    """`<br/>`, `<br>`, `<br />` separate the two halves of a multi-line
    label — replace with a single space so the result is a sensible
    one-line ref."""
    for br in ("<br/>", "<br>", "<br />", "<BR/>"):
        text = f'graph TD\nA["X{br}Y"] --> B\n'
        assert extract_edges(text) == [("X Y", "B")], f"failed for {br!r}"


def test_html_label_combined_tags_and_br():
    """Real-world Mermaid often combines bold + br: `<b>ID</b><br/>Title`."""
    text = 'graph TD\nA["<b>CAPP-2</b><br/>Authentication & Profile"] --> B\n'
    assert extract_edges(text) == [("CAPP-2 Authentication & Profile", "B")]


# ── class / classDef / style / subgraph (Mermaid styling, must be skipped) ────


def test_classdef_lines_skipped():
    text = (
        "graph TD\n"
        "classDef critical fill:#ffe9c2,stroke:#c2691a,stroke-width:3px,color:#000\n"
        "A --> B\n"
    )
    assert extract_edges(text) == [("A", "B")]


def test_class_assignment_skipped():
    """`class A,B critical` assigns nodes to a style class — must not
    be misread as edges."""
    text = (
        "graph TD\n"
        "A --> B\n"
        "class A,B critical\n"
    )
    assert extract_edges(text) == [("A", "B")]


def test_style_line_skipped():
    text = (
        "graph TD\n"
        "style A fill:#fff,stroke:#000\n"
        "A --> B\n"
    )
    assert extract_edges(text) == [("A", "B")]


# ── full real-world graph (regression: CAPP epic-deps spec) ───────────────────


def test_real_world_capp_graph():
    """The full graph the operator authored for the SportBuddies CAPP
    spec — labels carry HTML (CAPP-id + bold + br + title), edges carry
    text labels, and the block ends with classDef + class lines."""
    text = '''graph TD
    CAPP2["<b>CAPP-2</b><br/>Authentication & Profile"]
    CAPP4["<b>CAPP-4</b><br/>Court Discovery"]
    CAPP5["<b>CAPP-5</b><br/>Court Detail & Booking"]
    CAPP5A["<b>CAPP-5A</b><br/>Recurring Bookings"]
    CAPP6["<b>CAPP-6</b><br/>My Bookings"]
    CAPP10["<b>CAPP-10</b><br/>Player Notifications"]

    CAPP2 -->|session required| CAPP4
    CAPP4 -->|map -> court detail| CAPP5
    CAPP4 -.->|CAPP-054 join slot uses slot list| CAPP6
    CAPP5 -->|entry from court detail 07| CAPP5A
    CAPP5 -->|bookings & confirmed status| CAPP6
    CAPP5A -->|series rows in list| CAPP6
    CAPP5 -.->|booking status events| CAPP10
    CAPP6 -.->|deep-link target| CAPP10

    classDef critical fill:#ffe9c2,stroke:#c2691a,stroke-width:3px,color:#000
    classDef parallel fill:#e3f0ff,stroke:#1a66c2,stroke-width:2px,color:#000
    classDef cross fill:#f0e6ff,stroke:#6633b3,stroke-width:2px,color:#000

    class CAPP2,CAPP4,CAPP5,CAPP6 critical
    class CAPP5A parallel
    class CAPP10 cross
'''
    edges = extract_edges(text)
    expected = [
        ("CAPP-2 Authentication & Profile",  "CAPP-4 Court Discovery"),
        ("CAPP-4 Court Discovery",           "CAPP-5 Court Detail & Booking"),
        ("CAPP-4 Court Discovery",           "CAPP-6 My Bookings"),
        ("CAPP-5 Court Detail & Booking",    "CAPP-5A Recurring Bookings"),
        ("CAPP-5 Court Detail & Booking",    "CAPP-6 My Bookings"),
        ("CAPP-5A Recurring Bookings",       "CAPP-6 My Bookings"),
        ("CAPP-5 Court Detail & Booking",    "CAPP-10 Player Notifications"),
        ("CAPP-6 My Bookings",               "CAPP-10 Player Notifications"),
    ]
    assert edges == expected
