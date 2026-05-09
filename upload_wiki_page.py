#!/usr/bin/env python3
"""
Upload markdown files as Plane workspace wiki pages.

Usage:
    python3 sync_workspace_pages.py <file_or_dir> [file_or_dir ...]

Examples:
    python3 sync_workspace_pages.py SportBuddies/design/
    python3 sync_workspace_pages.py SportBuddies/business/colors.md
    python3 sync_workspace_pages.py SportBuddies/design/ SportBuddies/business/

Page names are derived from the first # H1 in each markdown file, falling back to the filename.
Tracks file → page UUID in .plane-workspace-pages.json (re-runs update instead of duplicate).
Credentials read from ~/.config/plane/config.json or env vars:
    PLANE_API_TOKEN, PLANE_HOST, PLANE_WORKSPACE
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import markdown
import requests

CONFIG_PATH = Path.home() / ".config" / "plane" / "config.json"
MAPPING_FILE = Path(".plane-workspace-pages.json")


def load_credentials():
    token = os.environ.get("PLANE_API_TOKEN")
    host = os.environ.get("PLANE_HOST", "https://api.plane.so")
    workspace = os.environ.get("PLANE_WORKSPACE")

    if not token and CONFIG_PATH.exists():
        cfg = json.loads(CONFIG_PATH.read_text())
        token = token or cfg.get("token")
        host = host or cfg.get("host", "https://api.plane.so")
        workspace = workspace or cfg.get("workspace")

    if not token or not workspace:
        sys.exit("ERROR: Missing PLANE_API_TOKEN or PLANE_WORKSPACE. Check ~/.config/plane/config.json")

    return token, host.rstrip("/"), workspace


def load_mapping():
    if MAPPING_FILE.exists():
        return json.loads(MAPPING_FILE.read_text())
    return {}


def save_mapping(mapping):
    MAPPING_FILE.write_text(json.dumps(mapping, indent=2))


def extract_title(text):
    for line in text.splitlines():
        line = line.strip().lstrip("\\").strip()
        if line.startswith("# "):
            return line[2:].strip()
    return None


def collect_files(paths):
    md_files = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            md_files.extend(sorted(p.glob("*.md")))
        elif p.suffix == ".md":
            md_files.append(p)
        else:
            print(f"SKIP {p} (not .md)")
    return md_files


def upload_page(session, host, workspace, name, html, page_id=None):
    payload = {"name": name, "description_html": html, "access": 0}
    base_url = f"{host}/api/v1/workspaces/{workspace}/pages/"

    if page_id:
        resp = session.patch(f"{base_url}{page_id}/", json=payload)
    else:
        resp = session.post(base_url, json=payload)

    return resp


def main():
    parser = argparse.ArgumentParser(description="Sync markdown files to Plane workspace wiki pages")
    parser.add_argument("paths", nargs="+", help="Files or directories to upload")
    parser.add_argument("--dry-run", action="store_true", help="Preview without making changes")
    args = parser.parse_args()

    token, host, workspace = load_credentials()
    mapping = load_mapping()
    files = collect_files(args.paths)

    if not files:
        sys.exit("No .md files found.")

    session = requests.Session()
    session.headers.update({"X-API-Key": token, "Content-Type": "application/json"})

    for md_path in files:
        text = md_path.read_text(encoding="utf-8")
        title = extract_title(text) or md_path.stem
        html = markdown.markdown(text, extensions=["tables", "fenced_code"])
        key = str(md_path)
        existing_id = mapping.get(key)

        action = "UPDATE" if existing_id else "CREATE"
        print(f"[{action}] {md_path} → \"{title}\"", end="")

        if args.dry_run:
            print(" (dry-run)")
            continue

        resp = upload_page(session, host, workspace, title, html, existing_id)

        if resp.status_code in (200, 201):
            page_id = resp.json().get("id", existing_id)
            mapping[key] = page_id
            save_mapping(mapping)
            print(f" ✓ {page_id}")
        else:
            print(f" ✗ HTTP {resp.status_code}: {resp.text[:120]}")


if __name__ == "__main__":
    main()
