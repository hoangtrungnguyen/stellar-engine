#!/usr/bin/env python3
"""Sync local markdown files to Plane project pages."""

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import markdown
    import requests
except ImportError:
    print("Missing deps. Run: pip install markdown requests")
    sys.exit(1)

CONFIG_FILE = Path.home() / ".config/plane/config.json"
MAPPING_FILE = Path(".plane-pages.json")


def load_config() -> dict:
    token = os.environ.get("PLANE_API_TOKEN")
    host = os.environ.get("PLANE_HOST")
    workspace = os.environ.get("PLANE_WORKSPACE")

    if not all([token, host, workspace]):
        if not CONFIG_FILE.exists():
            print(f"Config not found at {CONFIG_FILE}. Run 'plane init' first.")
            sys.exit(1)
        cfg = json.loads(CONFIG_FILE.read_text())
        token = token or cfg.get("token")
        host = host or cfg.get("host", "https://api.plane.so")
        workspace = workspace or cfg.get("workspace")

    return {"token": token, "host": host.rstrip("/"), "workspace": workspace}


def load_mapping() -> dict:
    if MAPPING_FILE.exists():
        return json.loads(MAPPING_FILE.read_text())
    return {}


def save_mapping(mapping: dict):
    MAPPING_FILE.write_text(json.dumps(mapping, indent=2))


def md_to_html(path: Path) -> tuple[str, str]:
    """Return (page_name, html). First H1 becomes the page name."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    name = path.stem
    for line in lines:
        if line.startswith("# "):
            name = line[2:].strip()
            break

    html = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "codehilite", "nl2br"],
    )
    return name, html


def api_headers(token: str) -> dict:
    return {"X-API-Key": token, "Content-Type": "application/json"}


def pages_url(cfg: dict, project_id: str, page_id: str = "") -> str:
    base = f"{cfg['host']}/api/v1/workspaces/{cfg['workspace']}/projects/{project_id}/pages/"
    return f"{base}{page_id}/" if page_id else base


def list_pages(cfg: dict, project_id: str) -> dict[str, str]:
    """Return {page_name: page_id} for all existing pages in the project."""
    resp = requests.get(
        pages_url(cfg, project_id),
        headers=api_headers(cfg["token"]),
    )
    resp.raise_for_status()
    data = resp.json()
    results = data if isinstance(data, list) else data.get("results", [])
    return {p["name"]: p["id"] for p in results}


def create_page(cfg: dict, project_id: str, name: str, html: str) -> str:
    resp = requests.post(
        pages_url(cfg, project_id),
        headers=api_headers(cfg["token"]),
        json={"name": name, "description_html": html},
    )
    resp.raise_for_status()
    return resp.json()["id"]


def update_page(cfg: dict, project_id: str, page_id: str, name: str, html: str):
    resp = requests.patch(
        pages_url(cfg, project_id, page_id),
        headers=api_headers(cfg["token"]),
        json={"name": name, "description_html": html},
    )
    resp.raise_for_status()


def sync_file(md_path: Path, project_id: str, cfg: dict, mapping: dict, dry_run: bool, remote_pages: dict):
    key = str(md_path)
    name, html = md_to_html(md_path)

    if key in mapping:
        page_id = mapping[key]
        action = "UPDATE"
        if not dry_run:
            update_page(cfg, project_id, page_id, name, html)
    elif name in remote_pages:
        page_id = remote_pages[name]
        action = "UPDATE (matched by name)"
        if not dry_run:
            update_page(cfg, project_id, page_id, name, html)
            mapping[key] = page_id
    else:
        action = "CREATE"
        if not dry_run:
            page_id = create_page(cfg, project_id, name, html)
            mapping[key] = page_id

    prefix = "[DRY RUN] " if dry_run else ""
    print(f"{prefix}{action}  {md_path}  →  '{name}'")


def main():
    parser = argparse.ArgumentParser(description="Sync markdown files to Plane pages")
    parser.add_argument("project_id", help="Plane project UUID (from 'plane projects list --json')")
    parser.add_argument("files", nargs="*", help="Markdown files or directories to sync")
    parser.add_argument("--dry-run", action="store_true", help="Preview without making changes")
    args = parser.parse_args()

    cfg = load_config()
    mapping = load_mapping()

    paths: list[Path] = []
    for f in args.files:
        p = Path(f)
        if p.is_dir():
            paths.extend(sorted(p.rglob("*.md")))
        elif p.suffix == ".md":
            paths.append(p)
        else:
            print(f"Skipping non-markdown file: {f}")

    if not paths:
        parser.print_help()
        sys.exit(1)

    remote_pages = {} if args.dry_run else list_pages(cfg, args.project_id)

    for path in paths:
        try:
            sync_file(path, args.project_id, cfg, mapping, args.dry_run, remote_pages)
        except requests.HTTPError as e:
            print(f"ERROR {path}: {e.response.status_code} {e.response.text}")

    if not args.dry_run:
        save_mapping(mapping)
        print(f"\nMapping saved to {MAPPING_FILE}")


if __name__ == "__main__":
    main()
