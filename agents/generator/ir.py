"""IR dataclasses for the Generator agent.

Two layers:

- **Source IR** (`Heading`, `Block`, `Section`) — produced by parsers in
  `agents/generator/parser/` from a raw source document. Serialised to
  `extract.json`.
- **Outline** (`DesignLink`, `Task`, `Story`, `Epic`, `Outline`) — produced by
  the LLM (Phase D) or manually via a Claude Code session. Serialised to
  `outline.json`. Render consumes this.

Both are pure dataclasses → `asdict()` for JSON round-trip; no external deps.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


# ── Source IR (extract.json) ──────────────────────────────────────────────────


@dataclass
class Heading:
    level: int          # 1..6
    text: str
    anchor: str         # line number (markdown) or page+y (PDF, future)


@dataclass
class Block:
    kind: str           # "paragraph" | "list" | "code" | "table"
    text: str
    anchor: str


@dataclass
class Section:
    heading: Heading
    blocks: list[Block] = field(default_factory=list)
    children: list["Section"] = field(default_factory=list)


# ── Outline (outline.json) ────────────────────────────────────────────────────


@dataclass
class DesignLink:
    url: str
    label: str | None = None


@dataclass
class Task:
    title: str


@dataclass
class Story:
    title: str
    description_md: str = ""
    depends_on: list[str] = field(default_factory=list)
    source_anchors: list[str] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    design_links: list[DesignLink] = field(default_factory=list)


@dataclass
class Epic:
    title: str
    summary: str = ""
    source_anchors: list[str] = field(default_factory=list)
    stories: list[Story] = field(default_factory=list)


@dataclass
class Outline:
    epics: list[Epic] = field(default_factory=list)
    confidence: float = 0.0


# ── JSON helpers ──────────────────────────────────────────────────────────────


def section_from_dict(d: dict[str, Any]) -> Section:
    return Section(
        heading=Heading(**d["heading"]),
        blocks=[Block(**b) for b in d.get("blocks", [])],
        children=[section_from_dict(c) for c in d.get("children", [])],
    )


def outline_from_dict(d: dict[str, Any]) -> Outline:
    def _task(t: Any) -> Task:
        # Accept either a plain string ("Task title") or a dict {"title": …}
        # so hand-written outlines can use the simpler shape.
        if isinstance(t, str):
            return Task(title=t)
        if isinstance(t, dict):
            return Task(title=t["title"])
        raise TypeError(f"task entry must be str or dict, got {type(t).__name__}")

    def _story(s: dict[str, Any]) -> Story:
        return Story(
            title=s["title"],
            description_md=s.get("description_md", ""),
            depends_on=list(s.get("depends_on", [])),
            source_anchors=list(s.get("source_anchors", [])),
            tasks=[_task(t) for t in s.get("tasks", [])],
            acceptance_criteria=list(s.get("acceptance_criteria", [])),
            design_links=[DesignLink(**dl) for dl in s.get("design_links", [])],
        )

    def _epic(e: dict[str, Any]) -> Epic:
        return Epic(
            title=e["title"],
            summary=e.get("summary", ""),
            source_anchors=list(e.get("source_anchors", [])),
            stories=[_story(s) for s in e.get("stories", [])],
        )

    return Outline(
        epics=[_epic(e) for e in d.get("epics", [])],
        confidence=float(d.get("confidence", 0.0)),
    )


def to_jsonable(obj: Any) -> Any:
    """Dataclass → plain dict/list/scalar tree (`asdict` already does this)."""
    return asdict(obj)
