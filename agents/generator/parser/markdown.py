"""Markdown source → Section IR (Phase B).

Line-based walker. Tracks an indentation-free section stack keyed by ATX
heading level (H1..H6). Captures blocks (paragraph, list, code, table)
under the current section. Anchors are 1-indexed line numbers, stored as
strings (`"L12"`).

Why not Python-Markdown / markdown-it? Specs are simple structurally —
headings + paragraphs + bulleted ACs + a few code/table blocks. A
hand-rolled walker is ~120 lines, has no external runtime cost, and
produces line anchors that survive HTML round-trip (Python-Markdown
would not give us source lines for free).
"""

from __future__ import annotations

import re
from pathlib import Path

from ..ir import Block, Heading, Section


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^(```+|~~~+)")
_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")


def parse_markdown(path: Path) -> Section:
    """Parse a markdown file into a Section tree.

    The returned root Section always has `heading.level == 0` and acts as
    a container — the file's H1s (and any orphaned content before the
    first heading) hang off `root.children` / `root.blocks`.
    """
    text = path.read_text()
    return parse_text(text, source_label=path.stem)


def parse_text(text: str, *, source_label: str = "root") -> Section:
    root = Section(heading=Heading(level=0, text=source_label, anchor="L1"))
    stack: list[Section] = [root]

    lines = text.splitlines()
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        line_no = i + 1
        anchor = f"L{line_no}"

        # 1. Fenced code block — consume until matching fence.
        m_fence = _FENCE_RE.match(line)
        if m_fence:
            fence = m_fence.group(1)
            body_lines: list[str] = []
            i += 1
            while i < n and not lines[i].startswith(fence[0] * len(fence)):
                body_lines.append(lines[i])
                i += 1
            i += 1  # consume closing fence
            stack[-1].blocks.append(Block(kind="code", text="\n".join(body_lines), anchor=anchor))
            continue

        # 2. Heading — pop stack to parent level, push new section.
        m_h = _HEADING_RE.match(line)
        if m_h:
            level = len(m_h.group(1))
            text_ = m_h.group(2).strip()
            new_section = Section(heading=Heading(level=level, text=text_, anchor=anchor))
            while stack and stack[-1].heading.level >= level:
                stack.pop()
            if not stack:
                stack.append(root)
            stack[-1].children.append(new_section)
            stack.append(new_section)
            i += 1
            continue

        # 3. Blank line — skip; terminates any open paragraph.
        if not line.strip():
            i += 1
            continue

        # 4. Table — consecutive `|...|` lines.
        if _TABLE_ROW_RE.match(line):
            rows: list[str] = []
            while i < n and _TABLE_ROW_RE.match(lines[i]):
                rows.append(lines[i])
                i += 1
            stack[-1].blocks.append(Block(kind="table", text="\n".join(rows), anchor=anchor))
            continue

        # 5. List — consecutive list items (treated as one block; bullets preserved).
        if _LIST_RE.match(line):
            items: list[str] = []
            while i < n and (_LIST_RE.match(lines[i]) or _is_list_continuation(lines[i])):
                items.append(lines[i])
                i += 1
            stack[-1].blocks.append(Block(kind="list", text="\n".join(items), anchor=anchor))
            continue

        # 6. Paragraph — consume consecutive non-blank, non-special lines.
        paras: list[str] = []
        while i < n and lines[i].strip() and not _is_block_start(lines[i]):
            paras.append(lines[i])
            i += 1
        if paras:
            stack[-1].blocks.append(
                Block(kind="paragraph", text="\n".join(paras), anchor=anchor)
            )

    return root


def _is_list_continuation(line: str) -> bool:
    """Indented continuation of the previous list item (4+ spaces or tab)."""
    return line.startswith("    ") or line.startswith("\t")


def _is_block_start(line: str) -> bool:
    return bool(
        _HEADING_RE.match(line)
        or _FENCE_RE.match(line)
        or _LIST_RE.match(line)
        or _TABLE_ROW_RE.match(line)
    )
