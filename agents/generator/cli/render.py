"""render — turn outline.json into one markdown draft per epic + manifest.json.

Reads `<work-dir>/outline.json`. Drafts land in `<work-dir>/drafts/` so a
run directory is self-contained; the operator copies one or more into
`systems/<Name>/business/` after review.

Exit codes:
  0  drafts + manifest.json written
  1  missing or invalid outline.json (also: --system-name not provided)
  2  filesystem write error
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

_AGENTS_DIR = Path(__file__).resolve().parent.parent.parent
if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="render",
        description="Render outline.json into one markdown draft per epic.",
    )
    p.add_argument("--work-dir", required=True,
                   help="Run directory (drafts/<project>/runs/<run_id>/)")
    p.add_argument("--system-name", required=True,
                   help="System name (rendered as H1)")
    p.add_argument("--source", default=None,
                   help="Original source path (frontmatter); falls back to "
                        "outline.json metadata if present")
    p.add_argument("--model", default="manual-claude-code",
                   help="Frontmatter generator_model (default: manual session)")
    p.add_argument("--model-version", default="n/a",
                   help="Frontmatter generator_model_version")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    work_dir = Path(args.work_dir)
    outline_path = work_dir / "outline.json"

    if not outline_path.exists():
        print(f"ERROR: outline.json not found: {outline_path}", file=sys.stderr)
        return 1

    try:
        payload = json.loads(outline_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read {outline_path}: {exc}", file=sys.stderr)
        return 1

    from generator.ir import outline_from_dict
    from generator.render import RenderMeta, render

    outline_blob = payload.get("outline", payload)
    try:
        outline_obj = outline_from_dict(outline_blob)
    except (KeyError, TypeError, ValueError) as exc:
        print(f"ERROR: invalid outline shape: {exc}", file=sys.stderr)
        return 1

    run_id = payload.get("run_id") or work_dir.name
    source = args.source or payload.get("source") or "unknown"

    meta = RenderMeta(
        source=source,
        run_id=run_id,
        confidence=outline_obj.confidence,
        model=args.model,
        model_version=args.model_version,
    )

    out_dir = work_dir / "drafts"
    try:
        drafts = render(outline_obj, system_name=args.system_name,
                        out_dir=out_dir, meta=meta)
    except OSError as exc:
        print(f"ERROR: cannot write drafts: {exc}", file=sys.stderr)
        return 2

    manifest = {
        "run_id": run_id,
        "source": source,
        "system_name": args.system_name,
        "confidence": outline_obj.confidence,
        "drafts": [
            {"path": str(d.path.relative_to(work_dir)),
             "epic_title": d.epic_title,
             "confidence": d.confidence}
            for d in drafts
        ],
    }
    manifest_path = work_dir / "manifest.json"
    try:
        manifest_path.write_text(json.dumps(manifest, indent=2))
    except OSError as exc:
        print(f"ERROR: cannot write manifest: {exc}", file=sys.stderr)
        return 2

    print(f"rendered {len(drafts)} draft(s) → {out_dir}")
    print(f"manifest → {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
