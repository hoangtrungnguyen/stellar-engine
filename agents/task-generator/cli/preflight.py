#!/usr/bin/env python3
"""taskgen-preflight: duplicate-page check + work-item-type lookup + label cache."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from plane_client import PlaneClient, PlaneClientError, load_credentials  # noqa: E402
from planner import (  # noqa: E402
    build_label_map,
    build_type_map,
    find_duplicate_pages,
    missing_required_types,
    sentinel_label_name,
)


def _fetch_existing_with_label(client, project_id: str, label_id: str) -> list[dict]:
    """Page through work-items filtered by label, returning a flat list."""
    items = client.search_work_items(project_id, labels=label_id, per_page=100)
    out: list[dict] = []
    for it in items:
        out.append({
            "id": it.get("id"),
            "name": it.get("name"),
            "type_id": it.get("type_id") or it.get("type"),
            "parent": it.get("parent") or it.get("parent_id"),
            "priority": it.get("priority"),
            "sequence_id": it.get("sequence_id"),
            "labels": it.get("labels") or [],
            "description_html": it.get("description_html") or "",
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Check for duplicate pages, then cache work-item-types and labels."
    )
    ap.add_argument("project_id")
    ap.add_argument("page_id")
    ap.add_argument("--work-dir", type=Path, required=True)
    ap.add_argument("--allow-duplicate-pages", action="store_true",
                    help="Bypass the duplicate-page halt and proceed anyway.")
    args = ap.parse_args()

    try:
        token, host, workspace = load_credentials()
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1

    client = PlaneClient(host=host, workspace=workspace, token=token)

    try:
        pages = client.list_pages(args.project_id)
    except PlaneClientError as e:
        print(f"list_pages failed: HTTP {e.status} on {e.url}", file=sys.stderr)
        return 1

    target_title, duplicates = find_duplicate_pages(pages, args.page_id)

    if duplicates and not args.allow_duplicate_pages:
        print(
            f"\nDuplicate page(s) detected for target page {args.page_id} "
            f"(title: {target_title!r}):",
            file=sys.stderr,
        )
        for d in duplicates:
            print(f"  - {d.get('id')}: {d.get('name')}", file=sys.stderr)
        print(
            "\nPlane's REST API does not support page delete/update — resolve via "
            "the Plane web UI, or re-run with --allow-duplicate-pages to proceed anyway.",
            file=sys.stderr,
        )
        return 3

    try:
        types = client.list_work_item_types(args.project_id)
        labels = client.list_labels(args.project_id)
    except PlaneClientError as e:
        print(f"preflight failed: HTTP {e.status} on {e.url}", file=sys.stderr)
        return 1

    type_map = build_type_map(types)
    missing = missing_required_types(type_map)
    if missing:
        print(
            f"WARNING: Plane work-item type(s) missing: {', '.join(missing)}. "
            f"Phase 1 (preview) tolerates this; Phase 2 writes will fail until "
            f"the type(s) are created in Plane (paid tier may be required).",
            file=sys.stderr,
        )

    label_map = build_label_map(labels)

    # Phase 4: ensure the per-page sentinel label exists; create if missing.
    sentinel_name = sentinel_label_name(args.page_id)
    sentinel_label_id: str | None = label_map.get(sentinel_name)
    if not sentinel_label_id:
        try:
            created = client.create_label(args.project_id, sentinel_name)
            sentinel_label_id = created.get("id")
            if sentinel_label_id:
                label_map[sentinel_name] = sentinel_label_id
                print(
                    f"Created sentinel label {sentinel_name!r} ({sentinel_label_id})",
                    file=sys.stderr,
                )
        except PlaneClientError as e:
            print(
                f"WARNING: could not create sentinel label {sentinel_name!r}: "
                f"HTTP {e.status} on {e.url}. Phase 4 reconciliation may not work.",
                file=sys.stderr,
            )

    # Phase 4: fetch existing items carrying the sentinel — used by render to
    # diff against the spec on re-runs.
    existing_plane: list[dict] = []
    if sentinel_label_id:
        try:
            existing_plane = _fetch_existing_with_label(
                client, args.project_id, sentinel_label_id,
            )
        except PlaneClientError as e:
            print(
                f"WARNING: could not list existing Plane items: HTTP {e.status} on {e.url}.",
                file=sys.stderr,
            )

    if duplicates and args.allow_duplicate_pages:
        print(
            f"WARNING: bypassed {len(duplicates)} duplicate page(s); "
            f"preview will surface them.",
            file=sys.stderr,
        )

    payload = {
        "project_id": args.project_id,
        "page_id": args.page_id,
        "target_title": target_title,
        "type_uuids": type_map,
        "missing_types": missing,
        "label_uuids": label_map,
        "sentinel_label_name": sentinel_name,
        "sentinel_label_id": sentinel_label_id,
        "existing_plane": existing_plane,
        "duplicates": duplicates,
        "duplicates_bypassed": bool(duplicates and args.allow_duplicate_pages),
    }
    args.work_dir.mkdir(parents=True, exist_ok=True)
    out = args.work_dir / "preflight.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(str(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
