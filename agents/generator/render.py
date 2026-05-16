"""Render an Outline IR into one markdown spec draft per epic.

The output format is the contract consumed by `agents/task-generator/parser.py`
(see `docs/task-generator/parser.md` and `docs/generator/plan.md` §E1):

  - H1 = system name
  - H2 per epic
  - Optional `**UI/UX Design:**` bullet list under H2 when `epic.design_links`
    is non-empty
  - H3 per story, optional `> Depends on: …` blockquote when story has deps
  - `**Acceptance Criteria:**` marker + bullet list under H3 when set
  - Optional H4 per task with AC bullets

Frontmatter keys: `generator_source`, `generator_run_id`,
`generator_confidence`, `generator_model`, `generator_model_version`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path

from .ir import DesignLink, Epic, Outline, Story, Task


# ── public API ────────────────────────────────────────────────────────────────


@dataclass
class RenderMeta:
    """Frontmatter values plumbed in from the run context."""

    source: str
    run_id: str
    confidence: float
    model: str = "manual-claude-code"   # default for Phase D-deferred manual outlines
    model_version: str = "n/a"
    today: _date | None = None          # injectable for stable test filenames


@dataclass
class RenderedDraft:
    """One emitted markdown file."""

    path: Path
    epic_title: str
    confidence: float


def render(outline: Outline, *, system_name: str, out_dir: Path,
           meta: RenderMeta) -> list[RenderedDraft]:
    """Render every epic in `outline` into `out_dir`. Returns one entry per file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    today = (meta.today or _date.today()).isoformat()
    drafts: list[RenderedDraft] = []
    for epic in outline.epics:
        slug = slugify(epic.title) or "untitled"
        filename = f"{today}-{slug}.md"
        path = out_dir / filename
        path.write_text(render_epic(epic, system_name=system_name, meta=meta))
        drafts.append(RenderedDraft(
            path=path, epic_title=epic.title, confidence=outline.confidence,
        ))
    return drafts


def render_epic(epic: Epic, *, system_name: str, meta: RenderMeta) -> str:
    parts: list[str] = [
        _frontmatter(meta),
        f"# {system_name}",
        "",
        f"## {epic.title}",
    ]
    if epic.summary:
        parts.extend(["", epic.summary])
    if epic.design_links:
        parts.extend(["", _design_block(epic.design_links)])
    for story in epic.stories:
        parts.extend(["", _story_block(story)])
    parts.append("")  # trailing newline
    return "\n".join(parts)


# ── helpers ───────────────────────────────────────────────────────────────────


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """Lowercase, alphanumeric-only, hyphen-separated."""
    return _SLUG_RE.sub("-", text.lower()).strip("-")


def _frontmatter(meta: RenderMeta) -> str:
    lines = [
        "---",
        f"generator_source: {meta.source}",
        f"generator_run_id: {meta.run_id}",
        f"generator_confidence: {meta.confidence:.2f}",
        f"generator_model: {meta.model}",
        f"generator_model_version: {meta.model_version}",
        "---",
    ]
    return "\n".join(lines)


def _design_block(links: list[DesignLink]) -> str:
    bullets: list[str] = ["**UI/UX Design:**"]
    for dl in links:
        if dl.label:
            bullets.append(f"- [{dl.label}]({dl.url})")
        else:
            bullets.append(f"- {dl.url}")
    return "\n".join(bullets)


def _story_block(story: Story) -> str:
    parts: list[str] = [f"### {story.title}"]
    if story.depends_on:
        parts.append(f"> Depends on: {', '.join(story.depends_on)}")
    if story.acceptance_criteria:
        parts.append("")
        parts.append("**Acceptance Criteria:**")
        for ac in story.acceptance_criteria:
            parts.append(f"- {ac}")
    for task in story.tasks:
        parts.append("")
        parts.append(_task_block(task))
    return "\n".join(parts)


def _task_block(task: Task) -> str:
    parts: list[str] = [f"#### {task.title}"]
    if task.ac:
        for ac in task.ac:
            parts.append(f"- {ac}")
    return "\n".join(parts)
