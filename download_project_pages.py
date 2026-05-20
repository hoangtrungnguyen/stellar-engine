#!/usr/bin/env python3
"""Download Plane project pages to local markdown files.

Output structure: <output-root>/<workspace>/<project-folder>/<page-slug>.md

`<project-folder>` is the project's short identifier (e.g. `CAPP`) when
the input resolves to one, else the UUID verbatim. Existing files are
overwritten.

Usage:
  python3 download_project_pages.py <project_ref> [--output-root systems] \
      [--page-id <PAGE_UUID>] [--dry-run]

`<project_ref>` accepts either a Plane project UUID or its short
identifier code (`CAPP`, `STELL`, …). The script resolves codes by
listing the workspace's projects and matching on `identifier`.

When `--page-id` is given, only that single page is downloaded — the
project page list is not enumerated.
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


# A canonical Plane project UUID looks like 8-4-4-4-12 hex chars.
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                      re.IGNORECASE)


def projects_url(cfg: dict) -> str:
    return f"{cfg['host']}/api/v1/workspaces/{cfg['workspace']}/projects/"


def list_projects(cfg: dict) -> list[dict]:
    resp = requests.get(projects_url(cfg), headers=api_headers(cfg["token"]))
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else data.get("results", [])


def resolve_project(cfg: dict, project_ref: str) -> tuple[str, str]:
    """Resolve a `project_ref` (UUID or identifier code) to `(uuid, code)`.

    - If `project_ref` is a UUID, the API is queried so we can also
      return the short identifier (used for the output folder name).
    - If `project_ref` is a code like `CAPP`, list projects and match
      on `identifier` (case-insensitive).

    Falls back to `(project_ref, project_ref)` when the API list is
    unavailable — keeps the script usable in offline / dry-run paths,
    but the caller may then 404 on the pages endpoint.
    """
    is_uuid = bool(_UUID_RE.match(project_ref))
    try:
        projects = list_projects(cfg)
    except requests.HTTPError:
        return project_ref, project_ref

    if is_uuid:
        for p in projects:
            if str(p.get("id")) == project_ref:
                code = p.get("identifier") or project_ref
                return project_ref, code
        # UUID not in this workspace; still let the caller try the API.
        return project_ref, project_ref

    needle = project_ref.casefold()
    for p in projects:
        ident = (p.get("identifier") or "").casefold()
        if ident == needle:
            return str(p["id"]), p["identifier"]
    raise SystemExit(
        f"ERROR: no project with identifier {project_ref!r} in workspace "
        f"{cfg['workspace']!r}. Pass a UUID or check the code."
    )


def pages_url(cfg: dict, project_id: str, page_id: str = "") -> str:
    base = f"{cfg['host']}/api/v1/workspaces/{cfg['workspace']}/projects/{project_id}/pages/"
    return f"{base}{page_id}/" if page_id else base


def list_pages(cfg: dict, project_id: str) -> list[dict]:
    resp = requests.get(pages_url(cfg, project_id), headers=api_headers(cfg["token"]))
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else data.get("results", [])


# Plane's page model exposes an `access` IntegerField with choices:
#   0 = Public  (visible to every workspace member)
#   1 = Private (visible only to creator + explicitly shared members)
# See github.com/makeplane/plane → apps/api/plane/db/models/page.py
#
# Older Plane versions occasionally omit the field entirely; treat
# missing-or-falsy as public so we don't accidentally hide content
# when running against an older self-hosted instance.
def is_public_page(page: dict) -> bool:
    """Return True when a Plane page is workspace-public.

    Default-safe: missing/None access is treated as public (older Plane
    schema didn't expose the field). Operators who actually want to
    exclude unsure-schema pages can fall back to `--include-private`
    to opt in to the older "download everything" behaviour.
    """
    access = page.get("access")
    if access is None:
        return True
    return access == 0


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


# Sentinel exit codes for resolve_page_by_name(). Caller maps these to
# the script's process-level exit codes. Defined here so unit tests can
# import the constants instead of hard-coding integers.
PAGE_NAME_NOT_FOUND = 1
PAGE_NAME_AMBIGUOUS = 2


class PageNameResolutionError(SystemExit):
    """Raised when --page-name cannot be resolved to a single page.

    `kind` is one of `PAGE_NAME_NOT_FOUND` / `PAGE_NAME_AMBIGUOUS` so the
    caller can decide on exit code + log shape without re-parsing the
    error message string.
    """

    def __init__(self, kind: int, message: str):
        super().__init__(message)
        self.kind = kind


def resolve_page_by_name(
    cfg: dict,
    project_uuid: str,
    project_code: str,
    name: str,
    *,
    include_private: bool,
) -> str:
    """Match a page by exact, case-sensitive name within a project.

    Honours the public-only default — private pages are excluded from
    the candidate pool unless `include_private=True`. Matches the
    listing flow's privacy semantics: a private page named 'Foo' is
    invisible to `--page-name Foo` unless the operator opts in.

    Raises `PageNameResolutionError` with `kind=PAGE_NAME_AMBIGUOUS`
    when multiple matches exist, or `kind=PAGE_NAME_NOT_FOUND` when
    no match. Returns the page UUID on a unique match.
    """
    all_pages = list_pages(cfg, project_uuid)
    candidates = all_pages if include_private else [
        p for p in all_pages if is_public_page(p)
    ]
    matches = [p for p in candidates if p.get("name") == name]

    if not matches:
        # Could be a name typo OR a private-page-collision: include a
        # hint about --include-private when there's a private page with
        # this exact name that we filtered out.
        hidden_private = [
            p for p in all_pages
            if p.get("name") == name and not is_public_page(p)
        ]
        hint = (
            f" (1 private page with this name exists — "
            f"pass --include-private to include it)"
            if hidden_private and not include_private
            else ""
        )
        raise PageNameResolutionError(
            PAGE_NAME_NOT_FOUND,
            f"ERROR: no page named {name!r} in project {project_code} "
            f"(case-sensitive match){hint}",
        )

    if len(matches) > 1:
        raise PageNameResolutionError(
            PAGE_NAME_AMBIGUOUS,
            f"ERROR: {len(matches)} pages named {name!r} in project "
            f"{project_code}. Use --page-id <uuid> to disambiguate.",
        )

    return matches[0]["id"]


def download_single_page(
    cfg: dict,
    project_uuid: str,
    project_code: str,
    page_id: str,
    output_root: str,
    *,
    dry_run: bool = False,
) -> Path:
    """Download one specific page. Returns the written file path
    (or the path that *would* be written, in dry-run mode)."""
    page = fetch_page(cfg, project_uuid, page_id) if not dry_run else \
        {"name": f"<dry-run page {page_id}>", "id": page_id}
    name = page.get("name") or "untitled"
    slug = slugify(name)
    out_dir = Path(output_root) / cfg["workspace"] / project_code
    out_path = out_dir / f"{slug}.md"
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(render_markdown(page, cfg, project_uuid))
    action = "OVERWRITE" if out_path.exists() and not dry_run else "WRITE"
    prefix = "[DRY RUN] " if dry_run else ""
    print(f"{prefix}{action}  '{name}'  →  {out_path}")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download Plane project pages to local markdown")
    parser.add_argument("project_id",
                        help="Plane project UUID or short identifier (e.g. CAPP)")
    parser.add_argument("--output-root", default="systems",
                        help="Root directory (default: systems/)")
    # `--page-id` and `--page-name` are alternative ways to point at one
    # specific page; rejecting both is cleaner than picking a precedence.
    page_target = parser.add_mutually_exclusive_group()
    page_target.add_argument("--page-id", default=None,
                             help="Download only this page UUID (skips listing the project)")
    page_target.add_argument("--page-name", default=None,
                             help="Download only the page with this exact "
                                  "(case-sensitive) name within the project. "
                                  "Stops with exit 2 if multiple pages share "
                                  "the name; use --page-id then.")
    parser.add_argument("--dry-run", action="store_true",
                        help="List pages without writing files")
    parser.add_argument("--include-private", action="store_true",
                        help="Also download private (access=1) pages. "
                             "Default behaviour is public-pages-only.")
    args = parser.parse_args(argv)

    cfg = load_config()
    try:
        project_uuid, project_code = resolve_project(cfg, args.project_id)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 1

    # `--page-name` resolves through the listing endpoint first, then
    # hands off to the single-page fast path. Name match is exact and
    # case-sensitive; private pages are excluded from candidates unless
    # `--include-private` is passed (mirrors the listing flow).
    target_page_id = args.page_id
    if args.page_name:
        try:
            target_page_id = resolve_page_by_name(
                cfg, project_uuid, project_code, args.page_name,
                include_private=args.include_private,
            )
        except PageNameResolutionError as e:
            print(e, file=sys.stderr)
            return 2 if e.kind == PAGE_NAME_AMBIGUOUS else 1
        except requests.HTTPError as e:
            print(f"ERROR listing pages to match --page-name: "
                  f"{e.response.status_code} {e.response.text}", file=sys.stderr)
            return 2

    # Single-page fast path. Reached via `--page-id` (explicit UUID) or
    # via `--page-name` (resolved above). The operator named exactly one
    # page either way — honour it regardless of access setting. The
    # public-only filter only gates the bulk listing path below.
    if target_page_id:
        try:
            download_single_page(cfg, project_uuid, project_code, target_page_id,
                                 args.output_root, dry_run=args.dry_run)
        except requests.HTTPError as e:
            print(f"ERROR fetching page {target_page_id}: "
                  f"{e.response.status_code} {e.response.text}", file=sys.stderr)
            return 2
        return 0

    # Full project listing.
    try:
        all_pages = list_pages(cfg, project_uuid)
    except requests.HTTPError as e:
        print(f"ERROR listing pages: {e.response.status_code} {e.response.text}", file=sys.stderr)
        return 2

    if args.include_private:
        pages = all_pages
        filter_note = "(public + private — --include-private)"
    else:
        pages = [p for p in all_pages if is_public_page(p)]
        hidden = len(all_pages) - len(pages)
        filter_note = (
            f"(public only; skipped {hidden} private page(s) — "
            f"pass --include-private to include them)"
            if hidden else "(public only)"
        )

    print(f"Pages to process: {len(pages)} of {len(all_pages)} total {filter_note}")

    out_dir = Path(args.output_root) / cfg["workspace"] / project_code
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
                full = fetch_page(cfg, project_uuid, page_id)
            except requests.HTTPError as e:
                print(f"ERROR  {name}: {e.response.status_code} {e.response.text}", file=sys.stderr)
                continue
            out_path.write_text(render_markdown(full, cfg, project_uuid))
            written += 1

        print(f"{prefix}{action}  '{name}'  →  {out_path}")

    summary = f"\n{written if not args.dry_run else len(seen)} pages → {out_dir}"
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
