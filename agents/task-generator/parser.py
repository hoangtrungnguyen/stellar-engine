"""HTML -> Markdown -> IR pipeline for the task-generator agent."""

from __future__ import annotations

import re

from markdownify import markdownify

from ir import EpicNode, ParseWarning, StoryNode, TaskNode

_TYPE_MARKER_RE = re.compile(r"^(Bug|P0|P1|Spike):\s+(.*)$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*)$")
_FENCE_RE = re.compile(r"^(```|~~~)")

_SPECIAL_SECTIONS = {
    "out of scope": "out_of_scope",
    "open questions": "open_questions",
    "risks": "risks",
}


def html_to_markdown(html: str) -> str:
    return markdownify(
        html,
        heading_style="ATX",
        escape_asterisks=False,
        escape_underscores=False,
        escape_misc=False,
    )


def _strip_fences(md: str) -> tuple[str, list[str]]:
    lines = md.splitlines(keepends=True)
    out_lines: list[str] = []
    blocks: list[str] = []
    in_fence = False
    marker: str | None = None
    current: list[str] = []
    for line in lines:
        m = _FENCE_RE.match(line.lstrip())
        if m:
            tok = m.group(1)
            if not in_fence:
                in_fence = True
                marker = tok
                current = [line]
                continue
            current.append(line)
            if tok == marker:
                blocks.append("".join(current))
                current = []
                in_fence = False
                marker = None
            continue
        if in_fence:
            current.append(line)
        else:
            out_lines.append(line)
    if in_fence:
        blocks.append("".join(current))
    return "".join(out_lines), blocks


def _strip_type_marker(text: str) -> tuple[str, str | None]:
    m = _TYPE_MARKER_RE.match(text)
    if m:
        return m.group(2).strip(), m.group(1)
    return text, None


def _build_ref_regex(workspace_prefix: str) -> re.Pattern:
    return re.compile(rf"\b{re.escape(workspace_prefix)}-\d+\b")


def parse(
    md: str,
    spec_page_url: str,
    spec_page_id: str,
    workspace_prefix: str = "STELLAR",
) -> tuple[list[EpicNode], list[ParseWarning]]:
    """Parse markdown into a list of epics. Each H2 becomes an epic.

    Returns ([epic, ...], warnings). When the page has no H2, returns
    [single_epic_from_H1] plus a `no_h2` warning.
    """
    md_clean, fenced_blocks = _strip_fences(md)
    ref_re = _build_ref_regex(workspace_prefix)

    epics: list[EpicNode] = []
    epic: EpicNode | None = None
    page_title: str | None = None
    current_story: StoryNode | None = None
    current_task: TaskNode | None = None
    current_section = "default"
    section_level: int | None = None
    warnings: list[ParseWarning] = []
    pending_lines: list[str] = []
    pending_target: str | None = None

    def flush() -> None:
        nonlocal pending_lines
        if not pending_lines:
            return
        text = "\n".join(pending_lines).strip()
        pending_lines = []
        if not text:
            return
        if pending_target == "epic" and epic is not None:
            epic.description_md = _append_md(epic.description_md, text)
        elif pending_target == "story" and current_story is not None:
            current_story.description_md = _append_md(current_story.description_md, text)
        elif pending_target == "task" and current_task is not None:
            current_task.description_md = _append_md(current_task.description_md, text)

    for line in md_clean.splitlines():
        h_match = _HEADING_RE.match(line)
        bullet_match = _BULLET_RE.match(line)

        if h_match:
            level = len(h_match.group(1))
            text = h_match.group(2).strip()
            normalized = text.lower()

            if current_section != "default" and section_level is not None and level <= section_level:
                flush()
                current_section = "default"
                section_level = None

            if normalized in _SPECIAL_SECTIONS:
                flush()
                current_section = _SPECIAL_SECTIONS[normalized]
                section_level = level
                current_story = None
                current_task = None
                pending_target = None
                continue

            if current_section == "out_of_scope":
                continue

            if level == 1:
                flush()
                page_title = text
                continue

            if level == 2:
                flush()
                title, type_marker = _strip_type_marker(text)
                epic = EpicNode(
                    title=title,
                    description_md="",
                    spec_page_url=spec_page_url,
                    spec_page_id=spec_page_id,
                    related_refs=ref_re.findall(title),
                )
                epics.append(epic)
                current_story = None
                current_task = None
                pending_target = "epic"
                continue

            if level == 3:
                flush()
                if epic is None:
                    warnings.append(ParseWarning(kind="orphan_story", detail=text))
                    current_story = None
                    pending_target = None
                    continue
                title, type_marker = _strip_type_marker(text)
                story = StoryNode(
                    title=title,
                    description_md="",
                    type_marker=type_marker,
                    related_refs=ref_re.findall(title),
                )
                epic.stories.append(story)
                current_story = story
                current_task = None
                pending_target = "story"
                continue

            pending_lines.append(line)
            continue

        if bullet_match:
            text = bullet_match.group(1).strip()
            if current_section == "open_questions":
                if epic is not None:
                    epic.open_questions.append(text)
                continue
            if current_section == "risks":
                if epic is not None:
                    epic.risks.append(text)
                continue
            if current_section == "out_of_scope":
                continue
            if current_story is None:
                pending_lines.append(line)
                continue
            flush()
            title, type_marker = _strip_type_marker(text)
            task = TaskNode(
                title=title,
                description_md="",
                type_marker=type_marker,
                related_refs=ref_re.findall(title),
            )
            current_story.tasks.append(task)
            current_task = task
            pending_target = "task"
            continue

        if current_section == "out_of_scope":
            continue
        if current_section in ("open_questions", "risks"):
            continue
        pending_lines.append(line)

    flush()

    if not epics:
        warnings.append(ParseWarning(kind="no_h2", detail="No H2 found; using H1 as single-epic fallback"))
        fallback = EpicNode(
            title=page_title or "",
            description_md="",
            spec_page_url=spec_page_url,
            spec_page_id=spec_page_id,
        )
        epics.append(fallback)

    if fenced_blocks:
        attached = "\n\n".join(b.rstrip() for b in fenced_blocks)
        epics[0].description_md = _append_md(epics[0].description_md, attached)

    return epics, warnings


def _append_md(existing: str, addition: str) -> str:
    if not existing:
        return addition
    return existing + "\n\n" + addition
