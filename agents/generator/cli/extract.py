"""extract — parse a source document into extract.json.

Reads <source> (markdown today), invokes the markdown parser, and writes
`<work-dir>/extract.json` containing the Section IR tree.

Exit codes:
  0  extract.json written
  1  bad source path / unsupported file type / missing work-dir
  2  parse failure or filesystem write error
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

# Allow direct invocation (`python3 agents/generator/cli/extract.py …`) by
# putting `agents/` on sys.path so `import generator.parser.markdown` works.
_AGENTS_DIR = Path(__file__).resolve().parent.parent.parent
if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="extract",
        description="Parse a source document into extract.json.",
    )
    p.add_argument("source", help="Path to source document (markdown today)")
    p.add_argument("--work-dir", required=True,
                   help="Run directory (drafts/<project>/runs/<run_id>/)")
    p.add_argument("--stdout", action="store_true",
                   help="Also print the resulting JSON to stdout")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    source = Path(args.source)
    if not source.exists():
        print(f"ERROR: source not found: {source}", file=sys.stderr)
        return 1
    if source.suffix.lower() != ".md":
        print(f"ERROR: only .md sources supported (got {source.suffix}); "
              "PDF / URL frontends are deferred.", file=sys.stderr)
        return 1

    work_dir = Path(args.work_dir)
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"ERROR: cannot create work-dir {work_dir}: {exc}", file=sys.stderr)
        return 1

    # Import here so `extract.py --help` works without the parser import path
    # being set up (handy in CI where tests resolve imports differently).
    from generator.parser.markdown import parse_markdown

    try:
        root = parse_markdown(source)
    except Exception as exc:
        print(f"ERROR: parse failure: {exc}", file=sys.stderr)
        return 2

    payload = {
        "source": str(source),
        "source_label": source.stem,
        "root": asdict(root),
    }

    out_path = work_dir / "extract.json"
    try:
        out_path.write_text(json.dumps(payload, indent=2))
    except OSError as exc:
        print(f"ERROR: cannot write {out_path}: {exc}", file=sys.stderr)
        return 2

    print(f"extract.json → {out_path}")
    if args.stdout:
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
