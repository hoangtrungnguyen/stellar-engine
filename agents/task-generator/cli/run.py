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

import dependency_analyzer  # noqa: E402
from parser import html_to_markdown, parse  # noqa: E402
from plane_client import PlaneClient, PlaneClientError, load_credentials  # noqa: E402
from planner import (  # noqa: E402
    DuplicatePageError,
    build_label_map,
    build_type_map,
    find_duplicate_pages,
    missing_required_types,
    plan_from_cached,
    sentinel_label_name,
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
    ap.add_argument("--no-dep-reorder", action="store_true",
                    help="Detect epic dependencies but keep markdown order "
                         "(default: reorder topologically when no cycle).")
    ap.add_argument("--allow-dep-cycles", action="store_true",
                    help="Continue when a cycle is detected (skips reorder).")
    ap.add_argument("--strict-deps", action="store_true",
                    help="Fail when a dependency ref cannot be resolved.")
    ap.add_argument(
        "--no-plane-relations", action="store_true",
        help="Skip Phase 6 — don't post Plane `blocking` relations even if "
             "dep_graph.json exists.",
    )
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
        project = client.get_project(args.project_id)
        types = client.list_work_item_types(args.project_id)
        labels = client.list_labels(args.project_id)
    except PlaneClientError as e:
        print(f"preflight failed: HTTP {e.status} on {e.url}", file=sys.stderr)
        return 1
    project_identifier = project.get("identifier", "") or ""

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

    sentinel_name = sentinel_label_name(args.page_id)
    sentinel_label_id = label_map.get(sentinel_name)
    if not sentinel_label_id:
        try:
            created = client.create_label(args.project_id, sentinel_name)
            sentinel_label_id = created.get("id")
            if sentinel_label_id:
                label_map[sentinel_name] = sentinel_label_id
                print(
                    f"Created sentinel label {sentinel_name!r}",
                    file=sys.stderr,
                )
        except PlaneClientError as e:
            print(
                f"WARNING: could not create sentinel label: HTTP {e.status} on {e.url}.",
                file=sys.stderr,
            )

    existing_plane: list[dict] = []
    if sentinel_label_id:
        try:
            from preflight import _fetch_existing_with_label
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

    preflight_payload = {
        "project_id": args.project_id,
        "project_identifier": project_identifier,
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
    (work_dir / "preflight.json").write_text(json.dumps(preflight_payload, indent=2), encoding="utf-8")

    # Step 5: parse
    md = html_to_markdown(page_payload["description_html"])
    epics, warnings = parse(
        md,
        spec_page_url=spec_url,
        spec_page_id=args.page_id,
        workspace_prefix=mapping.workspace_prefix,
    )

    # Step 5b: dependency analysis
    dep_graph, dep_warnings = dependency_analyzer.analyze(epics)
    warnings.extend(dep_warnings)

    if args.strict_deps and dep_graph.unresolved_refs:
        print(
            f"Unresolved dependency ref(s) under --strict-deps:",
            file=sys.stderr,
        )
        for u in dep_graph.unresolved_refs:
            print(
                f"  - epic {u['epic_idx'] + 1} ({u['epic_title']!r}) → {u['kind']} {u['raw_ref']!r}",
                file=sys.stderr,
            )
        return 7

    if dep_graph.cycles and not args.allow_dep_cycles:
        print("Dependency cycle(s) detected — refusing to proceed:", file=sys.stderr)
        for cyc in dep_graph.cycles:
            names = " -> ".join(epics[i].title for i in cyc + [cyc[0]])
            print(f"  - {names}", file=sys.stderr)
        print(
            "Resolve in the spec page (remove or rewrite the offending "
            "`> Depends on:` blockquotes), or re-run with --allow-dep-cycles "
            "to skip topological reordering.",
            file=sys.stderr,
        )
        return 7

    if not args.no_dep_reorder:
        epics = dependency_analyzer.reorder(epics, dep_graph)

    ir_payload = {
        "epics": [dataclasses.asdict(e) for e in epics],
        "warnings": [dataclasses.asdict(w) for w in warnings],
        "page_title": page_payload["title"],
    }
    (work_dir / "ir.json").write_text(json.dumps(ir_payload, indent=2), encoding="utf-8")

    # Translate edges' original epic indices into post-reorder ref_keys so the
    # Grava writer (which only sees plan_ops) can resolve them without knowing
    # the topo permutation.
    reordered = not args.no_dep_reorder and not dep_graph.cycles
    if reordered:
        inv_topo = [0] * len(epics)
        for new_idx, old_idx in enumerate(dep_graph.topo_order):
            inv_topo[old_idx] = new_idx
        def _to_ref(orig_idx: int) -> str:
            return f"epic:{inv_topo[orig_idx]}"
    else:
        def _to_ref(orig_idx: int) -> str:
            return f"epic:{orig_idx}"

    resolved_edges = [
        {
            "src_ref_key": _to_ref(e.src_epic_idx),
            "dst_ref_key": _to_ref(e.dst_epic_idx),
            "src_title": dep_graph.epic_titles_original[e.src_epic_idx]
            if e.src_epic_idx < len(dep_graph.epic_titles_original) else "",
            "dst_title": dep_graph.epic_titles_original[e.dst_epic_idx]
            if e.dst_epic_idx < len(dep_graph.epic_titles_original) else "",
            "source": e.source,
            "raw_ref": e.raw_ref,
        }
        for e in dep_graph.edges
    ]

    dep_payload = {
        "edges": [dataclasses.asdict(e) for e in dep_graph.edges],
        "resolved_edges": resolved_edges,
        "unresolved_refs": dep_graph.unresolved_refs,
        "cycles": dep_graph.cycles,
        "topo_order": dep_graph.topo_order,
        "original_order": dep_graph.original_order,
        "reordered": reordered,
        "epic_titles": [e.title for e in epics],
    }
    (work_dir / "dep_graph.json").write_text(json.dumps(dep_payload, indent=2), encoding="utf-8")

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
        spec_page_id=args.page_id,
        existing_plane=existing_plane,
        dep_graph=dep_graph,
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
    print(
        f"deps: edges={len(dep_graph.edges)} "
        f"unresolved={len(dep_graph.unresolved_refs)} "
        f"cycles={len(dep_graph.cycles)} "
        f"reordered={'yes' if dep_payload['reordered'] else 'no'}"
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
    write_argv = [
        "write.py",
        "--work-dir", str(work_dir),
        "--target-repo", str(mapping.repo),
        "--run-id", run_id,
        "--on-failure", args.on_failure,
        "--yes",
    ]
    if args.no_plane_relations:
        write_argv.append("--no-plane-relations")
    sys.argv = write_argv
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
