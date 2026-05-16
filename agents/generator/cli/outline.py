"""outline — turn extract.json into outline.json (epic/story/task hierarchy).

Exit codes:
  0  outline.json written
  1  missing ANTHROPIC_API_KEY
  2  LLM call failed
  3  invalid output shape

Phase A: argparse skeleton only — prints "phase A scaffold" and exits 0.
Phase D implements the real Anthropic SDK call (DEFERRED — see plan).
"""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="outline",
        description="Turn extract.json into outline.json via LLM (Phase D).",
    )
    p.add_argument("--work-dir", required=True,
                   help="Run directory (drafts/<project>/runs/<run_id>/)")
    p.add_argument("--model", default="claude-sonnet-4-5",
                   help="Anthropic model id")
    return p


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    print("phase A scaffold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
