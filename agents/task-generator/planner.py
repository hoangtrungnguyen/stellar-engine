"""Plane pre-flight + op queue + preview Markdown rendering."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from ir import (
    AddComment,
    CreateWorkItem,
    EpicNode,
    Op,
    ParseWarning,
    RunPlan,
    UpdateWorkItem,
)

REQUIRED_TYPES = ("epic", "story", "task")
RELATED_SENTINEL_OPEN = "<!-- task-generator:related -->"
RELATED_SENTINEL_CLOSE = "<!-- /task-generator:related -->"

# Phase 4: every Plane work item created by task-generator carries this
# sentinel label so re-runs can find existing items via label search.
SENTINEL_LABEL_PREFIX = "tg:src:"

# type_marker (parsed from spec like "P0:" / "Bug:") → Plane priority
_PRIORITY_FROM_MARKER = {
    "P0": "urgent",
    "P1": "high",
    "P2": "medium",
    "P3": "low",
}

# type_marker → label name (applied alongside the sentinel + priority)
_LABEL_FROM_MARKER = {
    "Bug": "bug",
    "Spike": "spike",
}


def sentinel_label_name(page_id: str) -> str:
    return f"{SENTINEL_LABEL_PREFIX}{page_id}"


def priority_from_marker(marker: str | None) -> str | None:
    if not marker:
        return None
    return _PRIORITY_FROM_MARKER.get(marker)


def label_from_marker(marker: str | None) -> str | None:
    if not marker:
        return None
    return _LABEL_FROM_MARKER.get(marker)


class PlannerError(Exception):
    pass


class DuplicatePageError(Exception):
    def __init__(self, target_page_id: str, target_title: str, duplicates: list[dict]):
        super().__init__(
            f"Duplicate page(s) detected for {target_title!r}: "
            + ", ".join(d.get("id", "?") for d in duplicates)
        )
        self.target_page_id = target_page_id
        self.target_title = target_title
        self.duplicates = duplicates


def normalize_title(title: str) -> str:
    return (title or "").strip().lower()


PUBLIC_ACCESS = 0
PRIVATE_ACCESS = 1
_LIVE_ACCESS = (PUBLIC_ACCESS, PRIVATE_ACCESS)


def _is_live_page(page: dict) -> bool:
    """Only live public(0) / private(1) pages count for dup detection.

    Archived (`archived_at` set) and deleted (`deleted_at` set) pages are
    ignored even when their `access` value is still public/private — operators
    don't want stale pages to block a fresh run.
    """
    if page.get("access") not in _LIVE_ACCESS:
        return False
    if page.get("archived_at"):
        return False
    if page.get("deleted_at"):
        return False
    return True


def find_duplicate_pages(pages: list[dict], target_page_id: str) -> tuple[str, list[dict]]:
    """Return (target_title, list_of_other_live_pages_sharing_title).

    Only public/private pages are considered. The target itself bypasses the
    live-only filter so the operator can still target an archived page if they
    explicitly pass its id.
    """
    target = next((p for p in pages if p.get("id") == target_page_id), None)
    if target is None:
        return "", []
    target_title = target.get("name", "") or ""
    norm = normalize_title(target_title)
    if not norm:
        return target_title, []
    duplicates = [
        {"id": p.get("id"), "name": p.get("name", ""), "access": p.get("access")}
        for p in pages
        if p.get("id") != target_page_id
        and _is_live_page(p)
        and normalize_title(p.get("name", "")) == norm
    ]
    return target_title, duplicates


def build_type_map(types: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for t in types:
        name = (t.get("name") or "").strip().lower()
        if name in REQUIRED_TYPES:
            out[name] = t.get("id", "")
    return out


def missing_required_types(type_map: dict[str, str]) -> list[str]:
    return [t for t in REQUIRED_TYPES if t not in type_map or not type_map[t]]


def assert_required_types(type_map: dict[str, str]) -> None:
    """Phase 2+ guard. Phase 1 (preview) calls `missing_required_types` instead."""
    missing = missing_required_types(type_map)
    if missing:
        raise PlannerError(
            f"Required Plane work-item type(s) missing: {', '.join(missing)}. "
            f"Enable Plane paid tier or create the type(s) in the project."
        )


def build_label_map(labels: list[dict]) -> dict[str, str]:
    return {(lbl.get("name") or ""): lbl.get("id", "") for lbl in labels if lbl.get("name")}


def plan_from_cached(
    epics: list[EpicNode],
    type_map: dict[str, str],
    label_map: dict[str, str],
    target_repo: Path,
    warnings: list[ParseWarning],
    run_id: str,
    page_title: str = "",
    duplicates_bypassed: list[dict] | None = None,
    spec_page_id: str = "",
    existing_plane: list[dict] | None = None,
) -> RunPlan:
    """Build the RunPlan from a list of epics. Phase 1 tolerates missing types.

    Renders one preview Markdown file per epic plus a master file linking to
    each. Returns the master preview path on `RunPlan.preview_path`.

    ref_key scheme (disambiguated for multi-epic): `epic:<i>`,
    `story:<i>.<j>`, `task:<i>.<j>.<k>`.

    `spec_page_id` is the Plane page UUID — used to compute the sentinel label
    name applied to every Plane create (Phase 4 idempotency).
    """
    sentinel = sentinel_label_name(spec_page_id) if spec_page_id else None

    def _create(node_kind, title, desc_md, type_key, parent_ref, ref_key, marker):
        labels: list[str] = []
        if sentinel:
            labels.append(sentinel)
        marker_label = label_from_marker(marker)
        if marker_label:
            labels.append(marker_label)
        return CreateWorkItem(
            node_kind=node_kind,
            title=title,
            description_html=_md_to_html(desc_md),
            type_id_key=type_key,
            parent_ref=parent_ref,
            ref_key=ref_key,
            label_keys=labels,
            priority=priority_from_marker(marker),
        )

    ops: list[Op] = []

    for i, epic in enumerate(epics):
        epic_ref = f"epic:{i}"
        ops.append(_create(
            "epic", epic.title, epic.description_md, "epic",
            None, epic_ref, marker=None,
        ))

        for j, story in enumerate(epic.stories):
            story_ref = f"story:{i}.{j}"
            ops.append(_create(
                "story", story.title, story.description_md, "story",
                epic_ref, story_ref, marker=story.type_marker,
            ))
            for k, task in enumerate(story.tasks):
                ops.append(_create(
                    "task", task.title, task.description_md, "task",
                    story_ref, f"task:{i}.{j}.{k}", marker=task.type_marker,
                ))

        if epic.open_questions:
            ops.append(AddComment(
                target_ref_key=epic_ref,
                comment_html=_section_comment("Open questions", epic.open_questions),
            ))
        if epic.risks:
            ops.append(AddComment(
                target_ref_key=epic_ref,
                comment_html=_section_comment("Risks", epic.risks),
            ))

        if epic.related_refs:
            ops.append(_related_update(epic_ref, epic.related_refs))
        for j, story in enumerate(epic.stories):
            if story.related_refs:
                ops.append(_related_update(f"story:{i}.{j}", story.related_refs))
            for k, task in enumerate(story.tasks):
                if task.related_refs:
                    ops.append(_related_update(f"task:{i}.{j}.{k}", task.related_refs))

    # Phase 4: build diff against existing Plane state if provided.
    diff = None
    if existing_plane is not None:
        from reconcile import build_diff
        diff = build_diff(
            plan_ops=ops,
            existing_plane=existing_plane,
            type_map=type_map,
        )

    master_path, per_epic_paths = _render_previews(
        epics=epics,
        ops=ops,
        type_map=type_map,
        warnings=warnings,
        target_repo=target_repo,
        run_id=run_id,
        page_title=page_title,
        duplicates_bypassed=duplicates_bypassed or [],
        diff=diff,
    )

    return RunPlan(
        plane_ops=ops,
        grava_ops=[],
        preview_path=master_path,
        warnings=warnings,
    )


def plan(
    epics: list[EpicNode],
    project_id: str,
    page_id: str,
    client,
    target_repo: Path,
    warnings: list[ParseWarning],
    run_id: str,
    page_title: str = "",
    allow_duplicate_pages: bool = False,
    require_types: bool = False,
) -> RunPlan:
    """Full live planner — runs all pre-flight reads against Plane.

    `require_types=True` (Phase 2+) raises on missing epic/story/task types.
    Phase 1 default (`require_types=False`) tolerates missing types and renders
    the preview anyway.
    """
    pages = client.list_pages(project_id)
    target_title, duplicates = find_duplicate_pages(pages, page_id)
    if duplicates and not allow_duplicate_pages:
        raise DuplicatePageError(page_id, target_title, duplicates)

    types = client.list_work_item_types(project_id)
    type_map = build_type_map(types)
    if require_types:
        assert_required_types(type_map)

    labels = client.list_labels(project_id)
    label_map = build_label_map(labels)

    return plan_from_cached(
        epics=epics,
        type_map=type_map,
        label_map=label_map,
        target_repo=target_repo,
        warnings=warnings,
        run_id=run_id,
        page_title=page_title or target_title,
        duplicates_bypassed=duplicates if allow_duplicate_pages else [],
        spec_page_id=page_id,
    )


def _md_to_html(md: str) -> str:
    """Minimal Markdown-to-HTML pass for description bodies. Phase 1 keeps it simple."""
    if not md:
        return ""
    paragraphs = [p.strip() for p in md.split("\n\n") if p.strip()]
    return "".join(f"<p>{_escape(p)}</p>" for p in paragraphs)


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br>")
    )


def _section_comment(label: str, bullets: list[str]) -> str:
    items = "".join(f"<li>{_escape(b)}</li>" for b in bullets)
    return f"<p><strong>{label}:</strong></p><ul>{items}</ul>"


def _related_update(ref_key: str, refs: list[str]) -> UpdateWorkItem:
    body = (
        f"\n\n{RELATED_SENTINEL_OPEN}\n"
        f"Related: {', '.join(refs)}\n"
        f"{RELATED_SENTINEL_CLOSE}"
    )
    return UpdateWorkItem(target_ref_key=ref_key, patch={"description_html_append": body})


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(title: str) -> str:
    slug = _SLUG_RE.sub("-", (title or "epic").lower()).strip("-")
    return slug[:60] or "epic"


def _render_previews(
    epics: list[EpicNode],
    ops: list[Op],
    type_map: dict[str, str],
    warnings: list[ParseWarning],
    target_repo: Path,
    run_id: str,
    page_title: str,
    duplicates_bypassed: list[dict],
    diff=None,
) -> tuple[Path, list[Path]]:
    """Render one preview per epic + a master overview. Return (master, [per_epic])."""
    preview_dir = target_repo / "runs" / "preview" / run_id
    preview_dir.mkdir(parents=True, exist_ok=True)

    page_slug = _slugify(page_title or (epics[0].title if epics else "preview"))
    missing_types = missing_required_types(type_map)
    create_count = sum(1 for op in ops if isinstance(op, CreateWorkItem))
    comment_count = sum(1 for op in ops if isinstance(op, AddComment))
    update_count = sum(1 for op in ops if isinstance(op, UpdateWorkItem))
    spec_url = epics[0].spec_page_url if epics else ""

    per_epic_paths: list[Path] = []
    for i, epic in enumerate(epics):
        epic_slug = _slugify(epic.title)
        epic_path = preview_dir / f"{page_slug}.epic-{i:02d}-{epic_slug}.preview.md"
        epic_path.write_text(_render_epic(i, epic, type_map, ops), encoding="utf-8")
        per_epic_paths.append(epic_path)

    master_path = preview_dir / f"{page_slug}.master.preview.md"
    lines: list[str] = []
    lines.append(f"# Master preview: {page_title or '(untitled)'}")
    lines.append("")
    lines.append(f"- Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    lines.append(f"- Spec page: {spec_url}")
    lines.append(f"- Epics: {len(epics)}")
    lines.append(f"- Plane ops: {len(ops)} ({create_count} create, {comment_count} comment, {update_count} update)")
    lines.append(f"- Warnings: {len(warnings)}")
    lines.append(f"- Duplicates bypassed: {len(duplicates_bypassed)}")
    if missing_types:
        lines.append(f"- ⚠️ Missing Plane types: {', '.join(missing_types)} (Phase 2 writes will fail until created)")
    lines.append("")

    if warnings:
        lines.append("## Warnings")
        lines.append("")
        for w in warnings:
            lines.append(f"- **{w.kind}**: {w.detail}")
        lines.append("")

    if diff is not None:
        counts = diff.counts()
        lines.append("## Reconciliation against existing Plane state")
        lines.append("")
        lines.append(
            f"- Create: {counts['create']} | Update: {counts['update']} | "
            f"No change: {counts['no_change']} | Orphan: {counts['orphan']}"
        )
        if counts["update"]:
            lines.append("")
            lines.append("**Updates** (existing items with drift; will be PATCHed):")
            for ref_key, entry in diff.by_ref_key.items():
                if entry.verdict != "update":
                    continue
                fields = ", ".join(entry.fields_changed)
                lines.append(f"- `{ref_key}` ({entry.existing_uuid}) — fields: {fields}")
        if counts["orphan"]:
            lines.append("")
            lines.append("**Orphans** (in Plane, missing from spec; never auto-deleted):")
            for o in diff.orphans:
                lines.append(f"- `{o.uuid}` (#{o.sequence_id}): {o.name!r}")
        lines.append("")

    if duplicates_bypassed:
        lines.append("## ⚠️ Bypassed duplicate pages")
        lines.append("")
        lines.append("These Plane pages share the target's title and were bypassed via `--allow-duplicate-pages`:")
        lines.append("")
        for d in duplicates_bypassed:
            lines.append(f"- `{d.get('id')}` — {d.get('name')}")
        lines.append("")

    lines.append("## Epics")
    lines.append("")
    if not epics:
        lines.append("_(none — page had no H2 headings)_")
    for i, (epic, epic_path) in enumerate(zip(epics, per_epic_paths)):
        story_count = len(epic.stories)
        task_count = sum(len(s.tasks) for s in epic.stories)
        rel_path = epic_path.name
        lines.append(f"### {i + 1}. [{epic.title}]({rel_path})")
        lines.append(f"- stories: {story_count}, tasks: {task_count}")
        if epic.related_refs:
            lines.append(f"- related: {', '.join(epic.related_refs)}")
        if epic.open_questions:
            lines.append(f"- open_questions: {len(epic.open_questions)}")
        if epic.risks:
            lines.append(f"- risks: {len(epic.risks)}")
        lines.append("")

    master_path.write_text("\n".join(lines), encoding="utf-8")
    return master_path, per_epic_paths


def _render_epic(idx: int, epic: EpicNode, type_map: dict[str, str], all_ops: list[Op]) -> str:
    lines: list[str] = []
    lines.append(f"# Epic [{idx}]: {epic.title}")
    lines.append("")
    lines.append(f"- ref_key: `epic:{idx}`")
    lines.append(f"- type_id: `{type_map.get('epic') or '(none — type missing)'}`")
    if epic.related_refs:
        lines.append(f"- related: {', '.join(epic.related_refs)}")
    lines.append("")

    if epic.description_md:
        lines.append("## Description")
        lines.append("")
        for ln in epic.description_md.splitlines():
            lines.append(f"  {ln}")
        lines.append("")

    if not epic.stories:
        lines.append("## Stories")
        lines.append("")
        lines.append("_(no stories)_")
        lines.append("")
    else:
        lines.append("## Stories")
        lines.append("")
        for j, story in enumerate(epic.stories):
            lines.append(f"### Story [{idx}.{j}]: {story.title}")
            lines.append(f"- ref_key: `story:{idx}.{j}`")
            lines.append(f"- type_id: `{type_map.get('story') or '(none — type missing)'}`")
            if story.type_marker:
                lines.append(f"- marker: `{story.type_marker}`")
            if story.related_refs:
                lines.append(f"- related: {', '.join(story.related_refs)}")
            if story.description_md:
                lines.append("")
                for ln in story.description_md.splitlines():
                    lines.append(f"  {ln}")
            if story.tasks:
                lines.append("")
                lines.append("Tasks:")
                for k, task in enumerate(story.tasks):
                    marker = f" [{task.type_marker}]" if task.type_marker else ""
                    refs = f"  ← related: {', '.join(task.related_refs)}" if task.related_refs else ""
                    lines.append(f"- ({idx}.{j}.{k}) {task.title}{marker}{refs}")
            lines.append("")

    if epic.open_questions or epic.risks:
        lines.append("## Epic comments")
        lines.append("")
        if epic.open_questions:
            lines.append("**Open questions:**")
            for q in epic.open_questions:
                lines.append(f"- {q}")
            lines.append("")
        if epic.risks:
            lines.append("**Risks:**")
            for r in epic.risks:
                lines.append(f"- {r}")
            lines.append("")

    epic_prefix = f"epic:{idx}"
    story_prefix = f"story:{idx}."
    task_prefix = f"task:{idx}."
    related_updates = [
        op for op in all_ops
        if isinstance(op, UpdateWorkItem)
        and (op.target_ref_key == epic_prefix
             or op.target_ref_key.startswith(story_prefix)
             or op.target_ref_key.startswith(task_prefix))
    ]
    if related_updates:
        lines.append("## Related-refs description updates")
        lines.append("")
        for op in related_updates:
            lines.append(f"- `{op.target_ref_key}`: {op.patch.get('description_html_append', '').strip()}")
        lines.append("")

    return "\n".join(lines)
