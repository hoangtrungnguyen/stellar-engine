#!/usr/bin/env python3
"""taskgen-fetch: fetch one Plane page's HTML + title; write to <work_dir>/page.json."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from plane_client import PlaneClient, PlaneClientError, load_credentials  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch one Plane page and write page.json.")
    ap.add_argument("project_id")
    ap.add_argument("page_id")
    ap.add_argument("--work-dir", type=Path, required=True)
    args = ap.parse_args()

    try:
        token, host, workspace = load_credentials()
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1

    client = PlaneClient(host=host, workspace=workspace, token=token)
    try:
        page = client.get_page(args.project_id, args.page_id)
    except PlaneClientError as e:
        print(f"fetch failed: HTTP {e.status} on {e.url}", file=sys.stderr)
        return 1

    spec_url = (
        f"https://app.plane.so/{workspace}/projects/{args.project_id}"
        f"/pages/{args.page_id}/"
    )
    payload = {
        "project_id": args.project_id,
        "page_id": args.page_id,
        "title": page.get("name", ""),
        "description_html": page.get("description_html", ""),
        "spec_page_url": spec_url,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    args.work_dir.mkdir(parents=True, exist_ok=True)
    out = args.work_dir / "page.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(str(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
