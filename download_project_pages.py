#!/usr/bin/env python3
"""Download Plane project pages to local markdown files.

Output structure: <output-root>/<workspace>/<project-id>/<page-slug>.md
Existing files are overwritten.

Usage:
  python3 download_project_pages.py <project_id> [--output-root systems] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
    from markdownify import markdownify as html_to_md
except ImportError:
    print("Missing deps. Run: pip install requests markdownify", file=sys.stderr)
    sys.exit(1)

CONFIG_FILE = Path.home() / ".config/plane/config.json"


def load_config() -> dict:
    token = os.environ.get("PLANE_API_TOKEN")
    host = os.environ.get("PLANE_HOST")
    workspace = os.environ.get("PLANE_WORKSPACE")

    if not all([token, host, workspace]):
        if CONFIG_FILE.exists():
            cfg = json.loads(CONFIG_FILE.read_text())
            token = token or cfg.get("token")
            host = host or cfg.get("host", "https://api.plane.so")
            workspace = workspace or cfg.get("workspace")

    if not all([token, host, workspace]):
        print("Missing Plane credentials. Set PLANE_API_TOKEN / PLANE_HOST / PLANE_WORKSPACE "
              f"or populate {CONFIG_FILE}.", file=sys.stderr)
        sys.exit(1)

    return {"token": token, "host": host.rstrip("/"), "workspace": workspace}


def slugify(name: str) -> str:
    s = re.sub(r"[^\w\s-]", "", name).strip().lower()
    s = re.sub(r"[-\s]+", "-", s)
    return s or "untitled"


def api_headers(token: str) -> dict:
    return {"X-API-Key": token, "Content-Type": "application/json"}


def pages_url(cfg: dict, project_id: str, page_id: str = "") -> str:
    base = f"{cfg['host']}/api/v1/workspaces/{cfg['workspace']}/projects/{project_id}/pages/"
    return f"{base}{page_id}/" if page_id else base


def list_pages(cfg: dict, project_id: str) -> list[dict]:
    resp = requests.get(pages_url(cfg, project_id), headers=api_headers(cfg["token"]))
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else data.get("results", [])


def fetch_page(cfg: dict, project_id: str, page_id: str) -> dict:
    resp = requests.get(pages_url(cfg, project_id, page_id), headers=api_headers(cfg["token"]))
    resp.raise_for_status()
    return resp.json()


def render_markdown(page: dict, cfg: dict, project_id: str) -> str:
    name = page.get("name") or "Untitled"
    html = page.get("description_html") or ""
    body = html_to_md(html, heading_style="ATX").strip() if html else ""

    frontmatter = (
        "---\n"
        f"plane_page_id: {page.get('id')}\n"
        f"plane_page_name: \"{name}\"\n"
        f"plane_workspace: {cfg['workspace']}\n"
        f"plane_project_id: {project_id}\n"
        f"downloaded_at: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n"
        "---\n\n"
    )
    return frontmatter + f"# {name}\n\n{body}\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Download Plane project pages to local markdown")
    parser.add_argument("project_id", help="Plane project UUID or shortcode")
    parser.add_argument("--output-root", default="systems",
                        help="Root directory (default: systems/)")
    parser.add_argument("--dry-run", action="store_true",
                        help="List pages without writing files")
    args = parser.parse_args()

    cfg = load_config()

    try:
        pages = list_pages(cfg, args.project_id)
    except requests.HTTPError as e:
        print(f"ERROR listing pages: {e.response.status_code} {e.response.text}", file=sys.stderr)
        sys.exit(2)

    out_dir = Path(args.output_root) / cfg["workspace"] / args.project_id
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    seen: set[str] = set()
    written = 0
    for page in pages:
        name = page.get("name") or "untitled"
        page_id = page.get("id") or ""
        slug = slugify(name)
        if slug in seen and page_id:
            slug = f"{slug}-{page_id[:8]}"
        seen.add(slug)

        out_path = out_dir / f"{slug}.md"
        action = "OVERWRITE" if out_path.exists() else "WRITE"
        prefix = "[DRY RUN] " if args.dry_run else ""

        if not args.dry_run:
            try:
                full = fetch_page(cfg, args.project_id, page_id)
            except requests.HTTPError as e:
                print(f"ERROR  {name}: {e.response.status_code} {e.response.text}", file=sys.stderr)
                continue
            out_path.write_text(render_markdown(full, cfg, args.project_id))
            written += 1

        print(f"{prefix}{action}  '{name}'  →  {out_path}")

    summary = f"\n{written if not args.dry_run else len(seen)} pages → {out_dir}"
    print(summary)


if __name__ == "__main__":
    main()
