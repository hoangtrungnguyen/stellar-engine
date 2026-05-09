#!/usr/bin/env python3
"""taskgen-run: end-to-end orchestrator.

Default flow: preview the plan, ask for confirmation, then invoke cli/write.py
to execute against Plane (Phase 2). `--dry-run` short-circuits after the preview.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parser import html_to_markdown, parse  # noqa: E402
from plane_client import PlaneClient, PlaneClientError, load_credentials  # noqa: E402
from planner import (  # noqa: E402
    DuplicatePageError,
    build_label_map,
    build_type_map,
    find_duplicate_pages,
    missing_required_types,
    plan_from_cached,
)
from repo_map import RepoMapError, lookup_project  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(
        description="task-generator: end-to-end orchestrator (preview + Phase-2 writes)."
    )
    ap.add_argument("project_id")
    ap.add_argument("page_id")
    ap.add_argument("--target-repo", type=Path, default=None)
    ap.add_argument("--no-clone", action="store_true")
    ap.add_argument("--allow-duplicate-pages", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="Preview only — skip Plane writes.")
    ap.add_argument("--no-grava", action="store_true", help="Skip Phase 3 Grava writes.")
    ap.add_argument("--yes", action="store_true", help="Skip interactive confirmation.")
    ap.add_argument("--on-failure", choices=["prompt", "rollback", "abort"], default="prompt",
                    help="Behaviour when a Plane op fails (Phase 2 writes).")
    ap.add_argument("--json-report", type=Path, default=None,
                    help="Override the default JSON report path.")
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args()

    # Step 1: resolve repo (clone if missing)
    try:
        mapping = lookup_project(
            args.project_id,
            override_repo=args.target_repo,
            allow_clone=not args.no_clone,
        )
    except KeyError as e:
        print(str(e), file=sys.stderr)
        return 1
    except RepoMapError as e:
        msg = str(e)
        print(msg, file=sys.stderr)
        if "missing locally" in msg or "--no-clone" in msg:
            return 2
        return 3
    if mapping.cloned:
        print(f"Cloned into {mapping.repo}", file=sys.stderr)

    # Step 2: init work dir
    run_id = args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    work_dir = mapping.repo / "runs" / "work" / run_id
    work_dir.mkdir(parents=True, exist_ok=True)

    # Credentials + client
    try:
        token, host, workspace = load_credentials()
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1
    client = PlaneClient(host=host, workspace=workspace, token=token)

    # Step 3: fetch page
    try:
        page = client.get_page(args.project_id, args.page_id)
    except PlaneClientError as e:
        print(f"fetch failed: HTTP {e.status} on {e.url}", file=sys.stderr)
        return 1
    spec_url = (
        f"https://app.plane.so/{workspace}/projects/{args.project_id}"
        f"/pages/{args.page_id}/"
    )
    page_payload = {
        "project_id": args.project_id,
        "page_id": args.page_id,
        "title": page.get("name", ""),
        "description_html": page.get("description_html", ""),
        "spec_page_url": spec_url,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (work_dir / "page.json").write_text(json.dumps(page_payload, indent=2), encoding="utf-8")

    # Step 4: preflight (dup check + types + labels)
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
            f"the type(s) are created in Plane.",
            file=sys.stderr,
        )
    label_map = build_label_map(labels)

    if duplicates and args.allow_duplicate_pages:
        print(
            f"WARNING: bypassed {len(duplicates)} duplicate page(s); "
            f"preview will surface them.",
            file=sys.stderr,
        )

    preflight_payload = {
        "project_id": args.project_id,
        "page_id": args.page_id,
        "target_title": target_title,
        "type_uuids": type_map,
        "missing_types": missing,
        "label_uuids": label_map,
        "duplicates": duplicates,
        "duplicates_bypassed": bool(duplicates and args.allow_duplicate_pages),
    }
    (work_dir / "preflight.json").write_text(json.dumps(preflight_payload, indent=2), encoding="utf-8")

    # Step 5: parse
    md = html_to_markdown(page_payload["description_html"])
    epics, warnings = parse(
        md,
        spec_page_url=spec_url,
        spec_page_id=args.page_id,
        workspace_prefix=mapping.workspace_prefix,
    )
    ir_payload = {
        "epics": [dataclasses.asdict(e) for e in epics],
        "warnings": [dataclasses.asdict(w) for w in warnings],
        "page_title": page_payload["title"],
    }
    (work_dir / "ir.json").write_text(json.dumps(ir_payload, indent=2), encoding="utf-8")

    # Step 6: render preview
    rp = plan_from_cached(
        epics=epics,
        type_map=type_map,
        label_map=label_map,
        target_repo=mapping.repo,
        warnings=warnings,
        run_id=run_id,
        page_title=page_payload["title"],
        duplicates_bypassed=duplicates if args.allow_duplicate_pages else [],
    )

    create_count = sum(1 for _ in rp.plane_ops if type(_).__name__ == "CreateWorkItem")
    update_count = sum(1 for _ in rp.plane_ops if type(_).__name__ == "UpdateWorkItem")
    comment_count = sum(1 for _ in rp.plane_ops if type(_).__name__ == "AddComment")

    print(f"master_preview: {rp.preview_path}")
    print(
        f"summary: epics={len(epics)} ops={len(rp.plane_ops)} "
        f"(create={create_count} comment={comment_count} update={update_count}) "
        f"warnings={len(warnings)} duplicates_bypassed={preflight_payload['duplicates_bypassed']}"
    )

    if args.dry_run:
        return 0

    if missing:
        print(
            f"Cannot write — Plane work-item type(s) missing: {', '.join(missing)}. "
            f"Create them in Plane first.",
            file=sys.stderr,
        )
        return 4

    if not args.yes:
        try:
            answer = input(
                f"Proceed with Plane writes ({len(epics)} epics, "
                f"{len(rp.plane_ops)} ops)? [y/N] "
            ).strip().lower()
        except EOFError:
            answer = ""
        if answer != "y":
            print("Aborted (no writes performed).", file=sys.stderr)
            return 0

    import write as write_cli
    sys.argv = [
        "write.py",
        "--work-dir", str(work_dir),
        "--target-repo", str(mapping.repo),
        "--run-id", run_id,
        "--on-failure", args.on_failure,
        "--yes",
    ]
    plane_rc = write_cli.main()
    if plane_rc != 0 or args.no_grava:
        return plane_rc

    import grava as grava_cli
    sys.argv = [
        "grava.py",
        "--work-dir", str(work_dir),
        "--target-repo", str(mapping.repo),
        "--run-id", run_id,
        "--on-failure", args.on_failure,
        "--yes",
    ]
    return grava_cli.main()


if __name__ == "__main__":
    sys.exit(main())
