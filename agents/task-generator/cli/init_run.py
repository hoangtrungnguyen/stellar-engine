#!/usr/bin/env python3
"""taskgen-init-run: create a work dir for this run; print its absolute path."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Create runs/work/<run_id>/ under the target repo; print its absolute path."
    )
    ap.add_argument("--target-repo", type=Path, required=True)
    ap.add_argument("--run-id", default=None,
                    help="Override the auto-generated YYYYMMDD-HHMMSS run id.")
    args = ap.parse_args()

    run_id = args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    work_dir = args.target_repo.resolve() / "runs" / "work" / run_id
    work_dir.mkdir(parents=True, exist_ok=True)
    print(str(work_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
