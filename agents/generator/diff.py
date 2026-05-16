"""Structured diff between two Outline IRs (current run vs previous).

Surfaces added / removed / renamed epics, stories, and tasks so the
operator sees the delta before promoting a re-run draft. No hard
failure — the diff is informational; render still emits new drafts.

Rename heuristic: an epic in "added" and one in "removed" whose
slugified titles differ by less than `_RENAME_RATIO` (Levenshtein-ish)
are reported as a single rename. Same logic at story level (within the
matched epic) and task level.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher

from .ir import Epic, Outline, Story, Task
from .render import slugify


_RENAME_RATIO = 0.6   # SequenceMatcher.ratio() threshold


# ── data ──────────────────────────────────────────────────────────────────────


@dataclass
class Rename:
    before: str
    after: str


@dataclass
class StoryDiff:
    epic: str
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    renamed: list[Rename] = field(default_factory=list)
    tasks_added: list[str] = field(default_factory=list)
    tasks_removed: list[str] = field(default_factory=list)


@dataclass
class OutlineDiff:
    epics_added: list[str] = field(default_factory=list)
    epics_removed: list[str] = field(default_factory=list)
    epics_renamed: list[Rename] = field(default_factory=list)
    story_diffs: list[StoryDiff] = field(default_factory=list)

    def is_empty(self) -> bool:
        return (
            not self.epics_added
            and not self.epics_removed
            and not self.epics_renamed
            and all(
                not sd.added and not sd.removed and not sd.renamed
                and not sd.tasks_added and not sd.tasks_removed
                for sd in self.story_diffs
            )
        )

    def to_dict(self) -> dict:
        return asdict(self)


# ── public API ────────────────────────────────────────────────────────────────


def diff_outlines(previous: Outline, current: Outline) -> OutlineDiff:
    prev_epics = {e.title: e for e in previous.epics}
    curr_epics = {e.title: e for e in current.epics}

    added_titles = [t for t in curr_epics if t not in prev_epics]
    removed_titles = [t for t in prev_epics if t not in curr_epics]
    renamed, added_titles, removed_titles = _pair_renames(added_titles, removed_titles)

    od = OutlineDiff(
        epics_added=added_titles,
        epics_removed=removed_titles,
        epics_renamed=renamed,
    )

    # Story + task diffs for epics that exist on both sides.
    for title, curr_epic in curr_epics.items():
        if title in prev_epics:
            sd = _diff_stories(prev_epics[title], curr_epic, epic_title=title)
            if (sd.added or sd.removed or sd.renamed
                    or sd.tasks_added or sd.tasks_removed):
                od.story_diffs.append(sd)

    # Renamed epics: compare stories using the after-title.
    for r in renamed:
        prev_epic = prev_epics[r.before]
        curr_epic = curr_epics[r.after]
        sd = _diff_stories(prev_epic, curr_epic, epic_title=r.after)
        if (sd.added or sd.removed or sd.renamed
                or sd.tasks_added or sd.tasks_removed):
            od.story_diffs.append(sd)

    return od


def render_diff_text(d: OutlineDiff) -> str:
    if d.is_empty():
        return "No changes vs previous run."

    lines: list[str] = []
    if d.epics_added:
        lines.append("Epics added:")
        lines.extend(f"  + {t}" for t in d.epics_added)
    if d.epics_removed:
        lines.append("Epics removed:")
        lines.extend(f"  - {t}" for t in d.epics_removed)
    if d.epics_renamed:
        lines.append("Epics renamed:")
        lines.extend(f"  ~ {r.before}  →  {r.after}" for r in d.epics_renamed)
    for sd in d.story_diffs:
        lines.append(f"Epic '{sd.epic}':")
        for t in sd.added:
            lines.append(f"  + story: {t}")
        for t in sd.removed:
            lines.append(f"  - story: {t}")
        for r in sd.renamed:
            lines.append(f"  ~ story: {r.before}  →  {r.after}")
        for t in sd.tasks_added:
            lines.append(f"  + task:  {t}")
        for t in sd.tasks_removed:
            lines.append(f"  - task:  {t}")
    return "\n".join(lines)


# ── internals ─────────────────────────────────────────────────────────────────


def _diff_stories(prev: Epic, curr: Epic, *, epic_title: str) -> StoryDiff:
    prev_stories = {s.title: s for s in prev.stories}
    curr_stories = {s.title: s for s in curr.stories}

    added = [t for t in curr_stories if t not in prev_stories]
    removed = [t for t in prev_stories if t not in curr_stories]
    renamed, added, removed = _pair_renames(added, removed)

    tasks_added: list[str] = []
    tasks_removed: list[str] = []
    for title, curr_story in curr_stories.items():
        if title in prev_stories:
            ta, tr = _diff_tasks(prev_stories[title], curr_story)
            tasks_added.extend(ta)
            tasks_removed.extend(tr)
    for r in renamed:
        ta, tr = _diff_tasks(prev_stories[r.before], curr_stories[r.after])
        tasks_added.extend(ta)
        tasks_removed.extend(tr)

    return StoryDiff(
        epic=epic_title,
        added=added, removed=removed, renamed=renamed,
        tasks_added=tasks_added, tasks_removed=tasks_removed,
    )


def _diff_tasks(prev: Story, curr: Story) -> tuple[list[str], list[str]]:
    prev_tasks = {t.title for t in prev.tasks}
    curr_tasks = {t.title for t in curr.tasks}
    return (
        sorted(curr_tasks - prev_tasks),
        sorted(prev_tasks - curr_tasks),
    )


def _pair_renames(added: list[str], removed: list[str]
                  ) -> tuple[list[Rename], list[str], list[str]]:
    """Greedy-pair added/removed titles whose slugs are similar."""
    if not added or not removed:
        return [], added, removed

    renames: list[Rename] = []
    used_added: set[str] = set()
    used_removed: set[str] = set()

    for r_title in removed:
        best_ratio = 0.0
        best_match: str | None = None
        for a_title in added:
            if a_title in used_added:
                continue
            ratio = SequenceMatcher(
                None, slugify(r_title), slugify(a_title)
            ).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = a_title
        if best_match and best_ratio >= _RENAME_RATIO:
            renames.append(Rename(before=r_title, after=best_match))
            used_added.add(best_match)
            used_removed.add(r_title)

    remaining_added = [t for t in added if t not in used_added]
    remaining_removed = [t for t in removed if t not in used_removed]
    return renames, remaining_added, remaining_removed
