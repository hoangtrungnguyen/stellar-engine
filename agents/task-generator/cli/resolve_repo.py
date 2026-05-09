#!/usr/bin/env python3
"""taskgen-resolve-repo: resolve a Plane project UUID to a sibling repo path (clone if missing)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from repo_map import RepoMapError, lookup_project  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Resolve a Plane project UUID to a sibling repo path. "
                    "Clones from git_url if the folder is missing."
    )
    ap.add_argument("project_id", help="Plane project UUID")
    ap.add_argument("--target-repo", type=Path, default=None,
                    help="Override the repo-map.yaml lookup; use this path directly.")
    ap.add_argument("--no-clone", action="store_true",
                    help="Do not clone if the sibling folder is missing.")
    ap.add_argument("--mapping-path", type=Path, default=None,
                    help="Override the repo-map.yaml location.")
    args = ap.parse_args()

    try:
        mapping = lookup_project(
            args.project_id,
            override_repo=args.target_repo,
            mapping_path=args.mapping_path,
            allow_clone=not args.no_clone,
        )
    except KeyError as e:
        print(str(e), file=sys.stderr)
        return 1
    except RepoMapError as e:
        msg = str(e)
        if "--no-clone" in msg or "missing locally" in msg:
            print(msg, file=sys.stderr)
            return 2
        print(msg, file=sys.stderr)
        return 3

    if mapping.cloned:
        print(f"Cloned into {mapping.repo}", file=sys.stderr)
    print(str(mapping.repo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
