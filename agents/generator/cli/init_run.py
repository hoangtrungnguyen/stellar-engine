"""init_run — provision drafts/<project>/runs/<run_id>/ for a new generator run.

Writes a minimal `run.json` stub into the new directory and prints the
run directory path on stdout (chainable: `WORK=$(se generate ... | …)`
or `WORK=$(init_run --project foo)`).

Exit codes:
  0  run directory created (path printed to stdout)
  1  argument or filesystem error
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_AGENTS_DIR = Path(__file__).resolve().parent.parent.parent
if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="init_run",
        description="Provision drafts/<project>/runs/<run_id>/ for a generator run.",
    )
    p.add_argument("--project", required=True, help="Project / system name (drafts subdir)")
    p.add_argument("--drafts-root", default="drafts",
                   help="Drafts root directory (default: drafts/)")
    p.add_argument("--run-id", default=None,
                   help="Override run ID (default: UTC timestamp)")
    p.add_argument("--source", default=None,
                   help="Optional: record source-doc path in run.json")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    run_id = args.run_id or _utc_run_id()
    work_dir = Path(args.drafts_root) / args.project / "runs" / run_id

    try:
        work_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"ERROR: cannot create {work_dir}: {exc}", file=sys.stderr)
        return 1

    run_meta = {
        "run_id": run_id,
        "project": args.project,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": args.source,
    }
    try:
        (work_dir / "run.json").write_text(json.dumps(run_meta, indent=2))
    except OSError as exc:
        print(f"ERROR: cannot write run.json: {exc}", file=sys.stderr)
        return 1

    print(str(work_dir))
    return 0


def _utc_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


if __name__ == "__main__":
    sys.exit(main())
