"""run — one-shot orchestrator chaining init_run → extract → outline → render.

This module is the canonical operator entry point:
    python3 agents/generator/cli/run.py <source> --project <NAME>

The previous `se generate` wrapper has been removed; invoke this script
directly. Inside Claude Code, the generator subagent
(`.claude/agents/generator.md`) still drives the full chain end-to-end.

Default mode is offline: extract.json is produced and the chain stops at
`outline` until either (a) `--llm` is passed (Phase D, deferred) or (b)
the operator has manually placed an `outline.json` in the run directory
(see plan §Phase D interim workflow).

If a previous run for the same source exists under
`drafts/<project>/runs/`, a structured diff (epics/stories/tasks
added/removed/renamed) is computed and printed before new drafts are
written. The diff is also persisted as `diff.json` next to the new
extract.

Exit codes:
  0  chain finished (or requested --step finished)
  1  argument error / missing inputs
  2  parse/render failure
  N  passthrough from a sub-step that exits with code N
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_AGENTS_DIR = Path(__file__).resolve().parent.parent.parent
if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))


# ── argparse ──────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run",
        description="Run the full generator chain (extract → outline → render).",
    )
    p.add_argument("source", help="Path to source document (markdown today)")
    p.add_argument("--project", required=True,
                   help="Project / system name (drafts subdir)")
    p.add_argument("--drafts-root", default="drafts",
                   help="Drafts root (default: drafts/)")
    p.add_argument("--system-name", default=None,
                   help="System H1 (default: --project value)")
    p.add_argument("--run-id", default=None,
                   help="Override run ID (default: UTC timestamp)")

    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--llm", action="store_true",
                      help="Call Anthropic API (Phase D, deferred — currently raises)")
    mode.add_argument("--no-llm", action="store_true",
                      help="Skip outline; produce extract.json only")
    mode.add_argument("--dry-run", action="store_true",
                      help="Extract only, do not render")

    p.add_argument("--step", choices=("extract", "outline", "render"), default=None,
                   help="Run a single step instead of the full chain")
    return p


# ── orchestrator ──────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    source = Path(args.source)
    if not source.exists():
        print(f"ERROR: source not found: {source}", file=sys.stderr)
        return 1

    from generator.cli import extract as extract_cli
    from generator.cli import init_run as init_run_cli
    from generator.cli import render as render_cli

    # 1. Init run dir.
    run_id = args.run_id or _utc_run_id()
    work_dir = Path(args.drafts_root) / args.project / "runs" / run_id
    rc = init_run_cli.main([
        "--project", args.project,
        "--drafts-root", args.drafts_root,
        "--run-id", run_id,
        "--source", str(source),
    ])
    if rc != 0:
        return rc

    if args.step == "outline":
        # No-op today (LLM deferred). Still 0 — operator will hand-write.
        print(f"step=outline: no-op (LLM deferred). Place outline.json into {work_dir}/")
        return 0

    if args.step == "render":
        return render_cli.main([
            "--work-dir", str(work_dir),
            "--system-name", args.system_name or args.project,
            "--source", str(source),
        ])

    # 2. Extract.
    rc = extract_cli.main([str(source), "--work-dir", str(work_dir)])
    if rc != 0:
        return rc

    if args.step == "extract" or args.dry_run or args.no_llm:
        print(f"stopped after extract. work_dir={work_dir}")
        return 0

    # 3. Outline — LLM deferred. Refuse loudly when --llm is set; otherwise
    #    stop so the operator can paste an outline.json into work_dir.
    if args.llm:
        from generator.llm_client import LLMNotEnabled, outline as _outline
        try:
            _outline(None)
        except LLMNotEnabled as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    outline_path = work_dir / "outline.json"
    if not outline_path.exists():
        print(
            "ERROR: no outline.json present and --llm not passed.\n"
            "       Place a hand-written outline.json into:\n"
            f"         {outline_path}\n"
            "       then re-run with --step render. See plan §Phase D.",
            file=sys.stderr,
        )
        return 1

    # 4. Diff vs previous run for the same source, if any.
    diff_path = work_dir / "diff.json"
    prev_run = _find_previous_run(work_dir.parent, source, current_run=run_id)
    if prev_run is not None:
        from generator.diff import diff_outlines, render_diff_text
        from generator.ir import outline_from_dict

        try:
            curr = outline_from_dict(_load_outline(outline_path))
            prev = outline_from_dict(_load_outline(prev_run / "outline.json"))
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            print(f"WARN: skipping diff (cannot read previous outline): {exc}",
                  file=sys.stderr)
        else:
            d = diff_outlines(prev, curr)
            print(f"Diff vs run {prev_run.name}:")
            print(render_diff_text(d))
            try:
                diff_path.write_text(json.dumps(d.to_dict(), indent=2))
            except OSError as exc:
                print(f"WARN: cannot write diff.json: {exc}", file=sys.stderr)

    # 5. Render.
    return render_cli.main([
        "--work-dir", str(work_dir),
        "--system-name", args.system_name or args.project,
        "--source", str(source),
    ])


# ── helpers ───────────────────────────────────────────────────────────────────


def _utc_run_id() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_outline(path: Path) -> dict:
    payload = json.loads(path.read_text())
    return payload.get("outline", payload)


def _find_previous_run(runs_dir: Path, source: Path,
                       *, current_run: str) -> Path | None:
    """Return the latest sibling run dir whose run.json points at `source`
    AND which has an outline.json on disk. Runs that stopped early
    (`--dry-run` / `--no-llm` / `--step extract`) are skipped so the diff
    lookup keeps walking back to the most recent fully-rendered run."""
    if not runs_dir.exists():
        return None
    candidates: list[Path] = []
    for child in sorted(runs_dir.iterdir(), reverse=True):
        if not child.is_dir() or child.name == current_run:
            continue
        if not (child / "outline.json").exists():
            continue
        run_meta = child / "run.json"
        if not run_meta.exists():
            continue
        try:
            meta = json.loads(run_meta.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if Path(meta.get("source") or "") == source:
            candidates.append(child)
    return candidates[0] if candidates else None


if __name__ == "__main__":
    sys.exit(main())
