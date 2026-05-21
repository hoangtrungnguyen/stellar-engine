#!/usr/bin/env python3
"""
`se orchestrator pr-watch` — single-shot driver for the PR-lifecycle watcher
(Phase D6 — replaces `agents/orchestrator/scripts/pr_merge_watcher.sh`).

Usage:
    pr_watch.py --once [--repo <path>] [--repos <path/to/repos.yaml>]
                       [--log-level INFO]

Modes:
    --repo <path>             scan exactly one repo
    --repos <repos.yaml>      scan every entry in repos.yaml (default
                              <cwd>/repos.yaml)
    (one of the two is required for any work to happen)

This wraps `runtime.pr_watcher.PRWatcher.tick()` so operators (and the
test suite) can drive a single tick without spinning up the full
daemon. The daemon's 300s pr-lifecycle ticker (D6) calls the same
`PRWatcher.tick()` — this CLI is parity testing + ad-hoc runs only.

Exit codes:
    0 = ok (every tick completed; empty events is valid)
    1 = unrecoverable error (missing repos.yaml, malformed YAML,
        grava not on PATH, etc.)
    2 = argparse error
"""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
import time
from pathlib import Path

# Make `runtime/*` importable when this script is run directly.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml not installed. Run: pip install pyyaml>=6.0",
          file=sys.stderr)
    sys.exit(1)

from runtime.pr_watcher import PRWatcher                               # noqa: E402

log = logging.getLogger("stellar.orchestrator.pr_watch")


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _resolve_targets(args: argparse.Namespace) -> list[Path]:
    """Return the list of repo paths to scan this run."""
    if args.repo:
        p = Path(args.repo).expanduser().resolve()
        if not p.is_dir():
            log.error("--repo %s is not a directory", p)
            sys.exit(1)
        return [p]

    repos_yaml = (Path(args.repos).expanduser().resolve()
                  if args.repos
                  else Path.cwd() / "repos.yaml")
    if not repos_yaml.is_file():
        log.error("repos.yaml not found at %s "
                  "(pass --repo PATH for a single repo, or "
                  "--repos PATH to point at a different yaml)",
                  repos_yaml)
        sys.exit(1)
    try:
        raw = yaml.safe_load(repos_yaml.read_text()) or {}
    except yaml.YAMLError as e:
        log.error("repos.yaml malformed: %s", e)
        sys.exit(1)

    out: list[Path] = []
    for name, cfg in (raw.get("repos") or {}).items():
        if not isinstance(cfg, dict) or not cfg.get("path"):
            log.warning("repos.yaml entry %r has no path; skipping", name)
            continue
        out.append(Path(cfg["path"]).expanduser().resolve())
    if not out:
        log.info("repos.yaml has 0 entries; nothing to do")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="se orchestrator pr-watch",
        description=(
            "Run one pr-lifecycle tick (or per-repo loop) against the "
            "registered repos. Replaces pr_merge_watcher.sh — same "
            "semantics (MERGED → close + signal, CLOSED → label + "
            "re-entry hint, OPEN → stale-check + comment-delta), but "
            "Python-native and centralised on the pr_state wisp schema."
        ),
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Required today. Reserved for future continuous-loop mode "
             "(use `se orchestrator run` for that). Present so cron / "
             "operator muscle memory matches the daemon's surface.",
    )
    target_group = parser.add_argument_group("targets",
                                             "Pick at most one")
    target_group.add_argument(
        "--repo", default=None, metavar="PATH",
        help="Scan exactly this repo. Bypasses repos.yaml.",
    )
    target_group.add_argument(
        "--repos", default=None, metavar="PATH",
        help="Scan every entry in this repos.yaml. Default: <cwd>/repos.yaml.",
    )
    parser.add_argument(
        "--log-level", default="INFO", dest="log_level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Log level (default: INFO).",
    )
    args = parser.parse_args(argv)
    _setup_logging(args.log_level)

    if not args.once:
        # Surface the future-vs-now distinction loudly so muscle memory
        # is corrected early.
        log.error("--once is required (continuous mode is `se orchestrator run`)")
        return 2

    if not shutil.which("grava"):
        log.error("grava not on PATH — pr-watcher cannot scan repos")
        return 1
    if not shutil.which("gh"):
        log.error("gh not on PATH — pr-watcher cannot fetch PR state")
        return 1

    repos = _resolve_targets(args)
    if not repos:
        return 0

    watcher = PRWatcher()
    total_events = 0
    started = int(time.time())
    log.info("scanning %d repo(s)", len(repos))
    for repo in repos:
        report = watcher.tick(repo)
        n = len(report.events)
        total_events += n
        log.info(
            "%s: scanned=%d events=%d skipped_no_pr=%d skipped_bad_url=%d",
            repo.name, report.issues_scanned, n,
            report.skipped_no_pr_number, report.skipped_bad_url,
        )
    elapsed = int(time.time()) - started
    log.info("done in %ds (total events: %d)", elapsed, total_events)
    return 0


if __name__ == "__main__":
    sys.exit(main())
