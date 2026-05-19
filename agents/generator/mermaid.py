"""Extract epic-dependency edges from a Mermaid `graph` / `flowchart` block.

The generator agent supports a small subset of Mermaid syntax — just
enough to recognise dependency edges between epics in the
`## Epic dependencies` section of a source markdown.

Supported subset (v1):

- Header: `graph TD`, `graph LR`, `graph BT`, `graph RL`, `graph TB`,
  `flowchart <dir>`. The direction is accepted but ignored — edges read
  left → right per arrow direction.
- Bare-ID node: `Authentication`. Used as the label verbatim.
- Labeled node: `A[Court Booking]`, `A(Court Booking)`, `A{Court Booking}`,
  `A["Court Booking"]` — bracket label wins; ID is discarded.
- Arrow variants: `-->`, `-.->`, `==>`, `-->|edge label|`. Style and
  label are stripped; treated as plain `A --> B`.
- Comments: `%% ...` lines are skipped.
- Undirected edges (`A --- B`), subgraphs, classDef, click handlers,
  and styling are silently skipped.

Direction semantics: `A --> B` reads "A leads to B" → A must be done
before B → **B depends on A**. The fold step (outline authoring)
inverts: for each edge `(src, dst)`, add `src` to
`Epic(title=dst).depends_on`.

API:

    extract_edges(text: str) -> list[tuple[str, str]]
        Returns [] if the input is not a recognisable
        `graph`/`flowchart` block. Each tuple is `(src_label, dst_label)`.
"""

from __future__ import annotations

import re


# ── grammar ───────────────────────────────────────────────────────────────────

_HEADER_RE = re.compile(r"^\s*(?:graph|flowchart)\s+\w+\s*$")
_COMMENT_RE = re.compile(r"^\s*%%")

# One node descriptor: an ID (letters/digits/underscore, leading non-digit)
# plus an optional shape wrapping a label: [Label], (Label), {Label}.
_NODE_PART = (
    r"([A-Za-z_]\w*)"
    r"(?:"
    r"\[([^\]]*)\]"
    r"|\(([^)]*)\)"
    r"|\{([^}]*)\}"
    r")?"
)

# An arrow with optional style + optional edge-label:
#   ==>     -->     -.->     ===>     -->|label|     -.->|label|
# Strict: must terminate in `>` (so undirected `---` is skipped).
_ARROW = (
    r"\s*"
    r"(?:={2,}|-+\.+-+|-+)"   # ===, -.-, ---, --, -
    r"\s*>"                   # arrow head
    r"\s*"
    r"(?:\|[^|]*\|\s*)?"      # optional `|edge label|`
)

_EDGE_RE = re.compile(rf"^\s*{_NODE_PART}{_ARROW}{_NODE_PART}\s*$")


# ── public API ────────────────────────────────────────────────────────────────


def extract_edges(text: str) -> list[tuple[str, str]]:
    """Parse a Mermaid `graph` / `flowchart` body into directed edges.

    Returns `[]` when the input is not recognisable as a Mermaid graph
    (e.g. empty, a `sequenceDiagram`, or a code block whose first line
    is not a `graph` / `flowchart` header). Each returned tuple is
    `(src_label, dst_label)` — extracted from a bracket label when
    present, otherwise from a previously-registered label for the same
    node ID, otherwise the bare node ID.

    Mermaid's node-vs-edge semantics: declaring `A[Foo]` once registers
    `A → "Foo"`. Subsequent edges that reference `A` bare resolve to
    `"Foo"`, even if the bracket is omitted on the later line.

    The function is silent: malformed lines are simply skipped so that
    a partly-broken graph still yields the edges it *can* parse.
    """
    lines = text.splitlines()

    # 1. Find the header line. If the first non-blank, non-comment line
    #    is not a `graph` / `flowchart` header, this is not a dependency
    #    graph — bail with [].
    header_idx = _find_header(lines)
    if header_idx is None:
        return []

    # 2. Scan the remainder for edges. Track id → label across lines so
    #    a label declared once propagates to later bare references.
    id_to_label: dict[str, str] = {}
    pending: list[tuple[str, str | None, str, str | None]] = []
    for line in lines[header_idx + 1:]:
        if _COMMENT_RE.match(line):
            continue
        m = _EDGE_RE.match(line)
        if not m:
            continue
        src_id, src_lb, src_lp, src_lc, dst_id, dst_lb, dst_lp, dst_lc = m.groups()
        src_label = _first_label(src_lb, src_lp, src_lc)
        dst_label = _first_label(dst_lb, dst_lp, dst_lc)
        if src_label is not None:
            id_to_label[src_id] = src_label
        if dst_label is not None:
            id_to_label[dst_id] = dst_label
        pending.append((src_id, src_label, dst_id, dst_label))

    return [
        (
            src_label if src_label is not None else id_to_label.get(src_id, src_id),
            dst_label if dst_label is not None else id_to_label.get(dst_id, dst_id),
        )
        for src_id, src_label, dst_id, dst_label in pending
    ]


# ── helpers ───────────────────────────────────────────────────────────────────


def _find_header(lines: list[str]) -> int | None:
    """Return the index of the `graph`/`flowchart` header, or None.

    A non-empty, non-comment line that is **not** a header proves this
    block is not a dependency graph (e.g. `sequenceDiagram`) — return
    None so the caller bails immediately.
    """
    for i, line in enumerate(lines):
        if not line.strip() or _COMMENT_RE.match(line):
            continue
        if _HEADER_RE.match(line):
            return i
        return None
    return None


def _first_label(*labels: str | None) -> str | None:
    """Return the first non-None label, normalised (whitespace + quotes
    trimmed). None if every label slot is empty.
    """
    for label in labels:
        if label is None:
            continue
        return label.strip().strip('"').strip()
    return None
