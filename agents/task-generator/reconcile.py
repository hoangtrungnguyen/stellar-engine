"""Phase 4: diff between IR plan and existing Plane state.

Joins planned `CreateWorkItem` ops to existing Plane work items by
`(node_kind, parent_uuid, normalized_title)`. Produces one verdict per
ref_key: `create | update(fields) | no_change`. Items in Plane that don't
match any planned op become `orphan`s.

The diff is consumed by the renderer (preview) and by the Plane writer
(`cli/write.py` + `plane_writer.execute`) to decide which ops to actually
fire — `no_change` is skipped, `update` becomes a PATCH, `create` is the
existing CREATE path.

A field comparison ignores the `description_html_append` sentinel block (the
Related: footer that the planner appends post-create); see _strip_related.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Literal

from ir import CreateWorkItem
from planner import RELATED_SENTINEL_CLOSE, RELATED_SENTINEL_OPEN

Verdict = Literal["create", "update", "no_change"]


@dataclass
class DiffEntry:
    ref_key: str
    verdict: Verdict
    existing_uuid: str | None = None
    existing_sequence_id: int | None = None
    fields_changed: list[str] = field(default_factory=list)
    # diff_detail[field] = {"from": <existing>, "to": <planned>}
    diff_detail: dict[str, dict] = field(default_factory=dict)


@dataclass
class OrphanEntry:
    uuid: str
    name: str
    sequence_id: int | None
    type_id: str | None
    parent_uuid: str | None


@dataclass
class ReconciliationDiff:
    by_ref_key: dict[str, DiffEntry] = field(default_factory=dict)
    orphans: list[OrphanEntry] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out = {"create": 0, "update": 0, "no_change": 0, "orphan": len(self.orphans)}
        for e in self.by_ref_key.values():
            out[e.verdict] = out.get(e.verdict, 0) + 1
        return out


def _norm_title(title: str) -> str:
    return (title or "").strip().lower()


_RELATED_BLOCK_RE = re.compile(
    re.escape(RELATED_SENTINEL_OPEN) + r".*?" + re.escape(RELATED_SENTINEL_CLOSE),
    re.DOTALL,
)


_EMPTY_HTML_VARIANTS = {"", "<p></p>", "<p><br></p>", "<p><br/></p>", "<p>&nbsp;</p>"}


def _strip_related(html: str) -> str:
    """Remove the `<!-- task-generator:related -->...</!-- ... -->` footer.

    The planner appends this block in a separate UpdateWorkItem op, so the
    initial create's description and the post-related description differ by
    exactly that block. Comparison ignores it to avoid false `update` verdicts.

    Also normalizes Plane's auto-generated empty-body variants (`<p></p>`,
    `<p><br></p>`, etc.) to "" so a planner-empty desc matches a
    Plane-default desc.
    """
    out = _RELATED_BLOCK_RE.sub("", html or "").strip()
    if out in _EMPTY_HTML_VARIANTS:
        return ""
    return out


def _norm_priority(value) -> str:
    if value is None:
        return "none"
    if isinstance(value, str):
        return value.lower() or "none"
    return str(value)


def build_diff(
    plan_ops: Iterable,
    existing_plane: list[dict],
    type_map: dict[str, str],
    ref_to_uuid_planned: dict[str, str] | None = None,
) -> ReconciliationDiff:
    """Compute the diff between planned creates and existing Plane items.

    `existing_plane`: list of dicts as written by `cli/preflight._fetch_existing_with_label`
    (each has `id`, `name`, `type_id`, `parent`, `priority`, `sequence_id`,
     `labels`, `description_html`).

    `type_map`: name → uuid (e.g. `{"epic": "t-epic", ...}`) — used to resolve
    each plan op's expected `type_id` for join-key comparison.

    `ref_to_uuid_planned`: optional pre-existing ref_key→uuid mapping from a
    prior run's state; used to short-circuit join (if we already know the
    Plane uuid for a ref_key, we trust it). Pass `None` for first-pass diffs.
    """
    plan_creates = [op for op in plan_ops if isinstance(op, CreateWorkItem)]

    # Index existing items by (type_id, parent_uuid, normalized_title). When
    # two items share a join key, pick the oldest by sequence_id; the loser
    # is added to `colliding` so it surfaces as an orphan instead of vanishing.
    by_join_key: dict[tuple, dict] = {}
    colliding: list[dict] = []
    for item in existing_plane:
        key = (item.get("type_id"), item.get("parent"), _norm_title(item.get("name")))
        existing = by_join_key.get(key)
        if existing is None:
            by_join_key[key] = item
            continue
        new_seq = item.get("sequence_id") or float("inf")
        old_seq = existing.get("sequence_id") or float("inf")
        if new_seq < old_seq:
            colliding.append(existing)
            by_join_key[key] = item
        else:
            colliding.append(item)

    # Walk plan: per op, find an existing match, classify.
    diff = ReconciliationDiff()
    matched_uuids: set[str] = set()

    # Build a transient ref_key → uuid lookup for parent resolution (uses
    # match results as we go).
    ref_to_uuid_match: dict[str, str] = dict(ref_to_uuid_planned or {})

    for op in plan_creates:
        type_id = type_map.get(op.type_id_key)
        parent_uuid = ref_to_uuid_match.get(op.parent_ref) if op.parent_ref else None
        key = (type_id, parent_uuid, _norm_title(op.title))
        existing = by_join_key.get(key)

        if existing is None:
            diff.by_ref_key[op.ref_key] = DiffEntry(
                ref_key=op.ref_key,
                verdict="create",
            )
            continue

        matched_uuids.add(existing["id"])
        ref_to_uuid_match[op.ref_key] = existing["id"]

        # Field comparison.
        fields_changed: list[str] = []
        diff_detail: dict[str, dict] = {}

        existing_title = existing.get("name") or ""
        # Equal under normalization (case + whitespace) → no drift. Operators
        # who want to change case must change the spec page; we don't propagate
        # cosmetic-only deltas.
        if _norm_title(op.title) != _norm_title(existing_title):
            fields_changed.append("title")
            diff_detail["title"] = {"from": existing_title, "to": op.title}

        existing_desc = _strip_related(existing.get("description_html") or "")
        planned_desc = _strip_related(op.description_html or "")
        if existing_desc != planned_desc:
            fields_changed.append("description_html")
            diff_detail["description_html"] = {
                "from": existing_desc[:200],
                "to": planned_desc[:200],
            }

        existing_pri = _norm_priority(existing.get("priority"))
        planned_pri = _norm_priority(op.priority or "none")
        if existing_pri != planned_pri:
            fields_changed.append("priority")
            diff_detail["priority"] = {"from": existing_pri, "to": planned_pri}

        verdict: Verdict = "update" if fields_changed else "no_change"
        diff.by_ref_key[op.ref_key] = DiffEntry(
            ref_key=op.ref_key,
            verdict=verdict,
            existing_uuid=existing["id"],
            existing_sequence_id=existing.get("sequence_id"),
            fields_changed=fields_changed,
            diff_detail=diff_detail,
        )

    # Orphans: existing items not matched by any plan op (including
    # collision losers).
    for item in existing_plane:
        if item["id"] in matched_uuids:
            continue
        diff.orphans.append(OrphanEntry(
            uuid=item["id"],
            name=item.get("name") or "",
            sequence_id=item.get("sequence_id"),
            type_id=item.get("type_id"),
            parent_uuid=item.get("parent"),
        ))

    return diff
