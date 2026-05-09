#!/usr/bin/env python3
"""taskgen-parse: HTML -> IR JSON. Reads page.json, writes ir.json."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parser import html_to_markdown, parse  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Parse page.json HTML into ir.json.")
    ap.add_argument("--work-dir", type=Path, required=True)
    ap.add_argument("--workspace-prefix", default="STELLAR")
    args = ap.parse_args()

    page_path = args.work_dir / "page.json"
    if not page_path.exists():
        print(f"page.json not found in {args.work_dir}", file=sys.stderr)
        return 1
    page = json.loads(page_path.read_text(encoding="utf-8"))

    md = html_to_markdown(page.get("description_html", ""))
    epics, warnings = parse(
        md,
        spec_page_url=page.get("spec_page_url", ""),
        spec_page_id=page.get("page_id", ""),
        workspace_prefix=args.workspace_prefix,
    )

    payload = {
        "epics": [dataclasses.asdict(e) for e in epics],
        "warnings": [dataclasses.asdict(w) for w in warnings],
        "page_title": page.get("title", ""),
    }
    out = args.work_dir / "ir.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(str(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
