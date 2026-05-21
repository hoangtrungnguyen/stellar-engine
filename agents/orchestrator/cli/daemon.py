#!/usr/bin/env python3
"""
`se orchestrator run` — long-running fleet daemon (Phase D1: tick loop).

Polls every repo in `repos.yaml` on a fixed cadence. For each repo, for
each team, checks the in-flight count against `repos.yaml#max_concurrent`
and dispatches Phase 0 for the next ready issue when there's room. The
daemon itself does NOT mutate grava state — it shells out to existing
per-team scripts (`fix_bug_claim.py`, `epic_task_claim.py`, `qa_load.py`,
`task_gen_expand.py`) which write the canonical wisps.

State machine:
    LOAD repos.yaml
      ↓
    ┌──── tick all repos ──────┐
    │  for repo in repos:      │
    │    if paused: skip       │
    │    counts = scan_inflight│
    │    for team in TEAMS:    │
    │      if inflight ≥ cap:  │
    │        skip team         │
    │      else:               │
    │        pick → dispatch   │
    │  write state file        │
    └──────────┬───────────────┘
               ↓
        sleep poll_interval  (skipped when --once)
               ↓
        SIGINT/SIGTERM? → drain + exit 0

Exit codes:
    0 = ok (graceful shutdown, --once finished, or empty repos.yaml)
    1 = unrecoverable error (e.g. repos.yaml unreadable, grava not on PATH)
    2 = argparse error

Out of scope for D1 (lands in later phases):
    D2: heartbeat watcher (stale-wisp surface)
    D3: failure-streak pause (auto-mark repo paused after N dispatch fails)
    D4: `se orchestrator status` reader
    D5: systemd / launchd units
    D6: pr-lifecycle ticker (absorbs pr_merge_watcher.sh — see
        [[pr-watcher-redesign]] in memory)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml not installed. Run: pip install pyyaml>=6.0",
          file=sys.stderr)
    sys.exit(1)

# Make the sibling `runtime/` package importable when daemon.py is run
# either as a script (`python3 daemon.py`) or loaded by cli/se's
# `_orch_invoke`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runtime.pr_watcher import PRWatcher                                # noqa: E402


# ── constants ─────────────────────────────────────────────────────────────────

TEAMS = ("fix-bug", "epic-task", "qa", "task-generator")

# pipeline_phase values that mean "this issue is NOT in-flight"
TERMINAL_PHASES = frozenset({"", "complete", "failed"})

# Per-team Phase 0 entry script. Lives in this same directory.
TEAM_PHASE0_SCRIPT = {
    "fix-bug":        "fix_bug_claim.py",
    "epic-task":      "epic_task_claim.py",
    "qa":             "qa_load.py",
    "task-generator": "task_gen_expand.py",
}

DEFAULT_POLL_INTERVAL = 60          # backlog ticker (D1) — matches repos.yaml default
PR_WATCHER_INTERVAL = 300           # pr-lifecycle ticker (D6) — matches old cron cadence
MIN_SLEEP_BETWEEN_TICKS = 5         # safety lower bound, even if config is broken
PAUSED_MARKER = ".grava/orchestrator-paused"

# State file location follows XDG; not configurable yet.
STATE_DIR_DEFAULT = Path.home() / ".local" / "share" / "stellar-engine"
STATE_FILE_NAME = "daemon.json"


log = logging.getLogger("stellar.orchestrator.daemon")


# ── data types ────────────────────────────────────────────────────────────────


@dataclass
class RepoConfig:
    """A single entry from repos.yaml."""
    name: str
    path: Path
    max_concurrent: int = 2
    poll_interval: int = DEFAULT_POLL_INTERVAL
    priority_threshold: str = "medium"


@dataclass
class TickResult:
    """Outcome of one tick across all repos. Drives logging + state file."""
    ts: int
    repos_polled: int = 0
    repos_paused: int = 0
    dispatches: int = 0
    skipped_capacity: int = 0
    skipped_blocked: int = 0     # Phase 0 claim exit 3 — unresolved blockers, NOT an error
    errors: list[str] = field(default_factory=list)


# ── repos.yaml loader (intentionally duplicated from cli/se) ──────────────────
#
# We could load `cli/se` as a module via importlib (the file has no .py
# suffix), but that pulls argparse + every other helper into the daemon
# process for one function. A 15-line re-implementation here keeps the
# daemon self-contained — easier to bench, easier to extract into
# agents/orchestrator/runtime.py when D2+ shares state-file logic.


def _load_repos(repos_yaml: Path) -> dict[str, RepoConfig]:
    if not repos_yaml.is_file():
        raise FileNotFoundError(
            f"repos.yaml not found at {repos_yaml}. "
            "Run `se init` then `se repos add` first."
        )
    raw = yaml.safe_load(repos_yaml.read_text()) or {}
    out: dict[str, RepoConfig] = {}
    for name, cfg in (raw.get("repos") or {}).items():
        if not isinstance(cfg, dict) or not cfg.get("path"):
            log.warning("repos.yaml entry %r has no path; skipping", name)
            continue
        out[name] = RepoConfig(
            name=name,
            path=Path(cfg["path"]).expanduser().resolve(),
            max_concurrent=int(cfg.get("max_concurrent", 2)),
            poll_interval=int(cfg.get("poll_interval", DEFAULT_POLL_INTERVAL)),
            priority_threshold=str(cfg.get("priority_threshold", "medium")),
        )
    return out


# ── grava adapters (subprocess; replace with runtime.adapters in D6) ─────────


def _grava_list_active(repo: Path) -> list[dict]:
    """Return all non-closed issues in `repo` as a list of dicts.

    The in-flight scan must see both `open` AND `in_progress` issues
    (Phase 0 claim moves them to `in_progress`, but they're still
    counted against max_concurrent). `grava list` with no `--status`
    filter returns everything non-archived; we drop the `closed` ones
    in Python since `--status` only accepts a single value.
    """
    r = subprocess.run(
        ["grava", "list", "--json"],
        cwd=str(repo),
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        log.warning("grava list failed in %s (exit %d): %s",
                    repo, r.returncode, (r.stderr or "").strip())
        return []
    try:
        data = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        log.warning("grava list returned non-JSON in %s", repo)
        return []
    if isinstance(data, dict):
        data = data.get("issues") or data.get("Issues") or []
    if not isinstance(data, list):
        return []
    # Drop closed; keep open + in_progress (and any other non-terminal
    # status grava grows in the future — being permissive here matches
    # the daemon's "in-flight = anything still moving" semantic).
    return [it for it in data
            if (it.get("status") or "").lower() != "closed"]


def _wisp_read(repo: Path, issue_id: str, key: str) -> str:
    """Return wisp value or "" if unset / missing."""
    r = subprocess.run(
        ["grava", "wisp", "read", issue_id, key],
        cwd=str(repo),
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return ""
    return (r.stdout or "").strip()


def _scan_inflight(repo: Path) -> dict[str, int]:
    """Single-pass scan of active (non-closed) issues: returns
    `{team: in_flight_count}`.

    An issue is in-flight when `pipeline_phase` wisp is set AND not in
    {"", "complete", "failed"}, AND has a `team` wisp. Phase 0 claim
    flips an issue from `open` → `in_progress`, so the scan covers
    BOTH states (D1 originally queried only `--status open` and missed
    in-flight claims — surfaced during dogfood 2026-05-21).

    Two wisp reads per active issue. The obvious O(N) approach the
    daemon-plan flags for benching — fine for D1, optimise in a later
    phase if it stings.
    """
    counts: dict[str, int] = {team: 0 for team in TEAMS}
    for it in _grava_list_active(repo):
        iid = it.get("id") or it.get("ID") or ""
        if not iid:
            continue
        phase = _wisp_read(repo, iid, "pipeline_phase")
        if phase in TERMINAL_PHASES:
            continue
        team = _wisp_read(repo, iid, "team")
        if team in counts:
            counts[team] += 1
    return counts


# ── pick + dispatch (subprocess to existing per-team scripts) ────────────────


def _script_path(name: str) -> Path:
    """Resolve a sibling orchestrator script."""
    return Path(__file__).resolve().parent / name


def _pick_ready(repo: Path, team: str) -> Optional[str]:
    """Call pick_ready.py for one team; return next issue id or None."""
    script = _script_path("pick_ready.py")
    if not script.is_file():
        log.error("pick_ready.py missing at %s", script)
        return None
    r = subprocess.run(
        [sys.executable, str(script),
         "--team", team, "--target-repo", str(repo), "--limit", "1"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        log.warning("pick_ready --team %s failed in %s (exit %d): %s",
                    team, repo, r.returncode, (r.stderr or "").strip())
        return None
    try:
        items = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        log.warning("pick_ready returned non-JSON for team %s in %s",
                    team, repo)
        return None
    if not items:
        return None
    return items[0].get("id") or items[0].get("ID")


def _dispatch_phase0(repo: Path, team: str, issue_id: str) -> int:
    """Fire Phase 0 for `team`. Returns exit code from the team script."""
    script_name = TEAM_PHASE0_SCRIPT.get(team)
    if not script_name:
        log.error("no Phase 0 script for team %r", team)
        return 1
    script = _script_path(script_name)
    if not script.is_file():
        log.error("%s missing at %s", script_name, script)
        return 1
    log.info("dispatch %s phase0 %s/%s", team, repo.name, issue_id)
    r = subprocess.run(
        [sys.executable, str(script), issue_id, "--target-repo", str(repo)],
    )
    return r.returncode


# ── state file (atomic write) ─────────────────────────────────────────────────


def _write_state(state_dir: Path, payload: dict) -> None:
    """Write daemon state JSON atomically. Best-effort: never raise to caller."""
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        target = state_dir / STATE_FILE_NAME
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        os.replace(tmp, target)
    except OSError as e:
        log.warning("state file write failed: %s", e)


# ── per-tick logic ────────────────────────────────────────────────────────────


def _is_paused(repo: Path) -> bool:
    return (repo / PAUSED_MARKER).exists()


def _tick(repos: dict[str, RepoConfig]) -> TickResult:
    """Run one full pass over all repos. Returns a TickResult summary."""
    result = TickResult(ts=int(time.time()))
    for name, cfg in repos.items():
        result.repos_polled += 1
        if _is_paused(cfg.path):
            log.info("%s: paused (skip)", name)
            result.repos_paused += 1
            continue
        if not cfg.path.is_dir():
            log.warning("%s: path %s missing (skip)", name, cfg.path)
            result.errors.append(f"{name}:missing_path")
            continue

        counts = _scan_inflight(cfg.path)
        log.debug("%s: inflight %s (cap=%d)", name, dict(counts),
                  cfg.max_concurrent)

        for team in TEAMS:
            if counts[team] >= cfg.max_concurrent:
                result.skipped_capacity += 1
                continue
            issue_id = _pick_ready(cfg.path, team)
            if not issue_id:
                continue
            rc = _dispatch_phase0(cfg.path, team, issue_id)
            if rc == 0:
                result.dispatches += 1
                # Don't immediately re-scan; this issue is now counted
                # for the next tick. Within this tick, increment locally
                # so we don't overshoot max_concurrent on the same team.
                counts[team] += 1
            elif rc == 3:
                # Hard-reject for unresolved blockers. NOT an error — the
                # loop continues to the next ready issue. `grava ready`
                # normally filters blocked items, so this fires only on a
                # rare race where a blocker was added between pick and
                # dispatch. Don't increment counts[team]: no claim happened.
                log.info("%s: %s phase0 for %s skipped (blocked by deps)",
                         name, team, issue_id)
                result.skipped_blocked += 1
            else:
                log.warning("%s: %s phase0 for %s exited %d",
                            name, team, issue_id, rc)
                result.errors.append(f"{name}:{team}:{issue_id}:exit{rc}")
    return result


# ── main loop ─────────────────────────────────────────────────────────────────


class _Shutdown:
    """Tiny shutdown-signal latch shared with SIGINT/SIGTERM handlers."""
    def __init__(self) -> None:
        self.stop = False

    def request(self, signum: int, _frame) -> None:
        # signal handlers must be tiny — flip flag, log, return.
        log.info("received signal %d; finishing current tick then exiting",
                 signum)
        self.stop = True


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _resolve_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    """Return (repos_yaml, state_dir) using --repos override or cwd default."""
    if args.repos:
        repos_yaml = Path(args.repos).expanduser().resolve()
    else:
        repos_yaml = Path.cwd() / "repos.yaml"
    state_dir = STATE_DIR_DEFAULT
    return repos_yaml, state_dir


def _min_poll_interval(repos: dict[str, RepoConfig]) -> int:
    """D1 ticks all repos at the min cadence across the fleet. Per-repo
    timing comes in a later phase. Lower bound enforced for safety."""
    if not repos:
        return DEFAULT_POLL_INTERVAL
    return max(MIN_SLEEP_BETWEEN_TICKS,
               min(r.poll_interval for r in repos.values()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="se orchestrator run",
        description=(
            "Continuous-loop fleet daemon for stellar-engine. Polls "
            "repos.yaml, dispatches ready issues to teams, respects "
            "per-repo max_concurrent caps."
        ),
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run a single tick then exit. Useful for cron mode and CI.",
    )
    parser.add_argument(
        "--repos", default=None, metavar="PATH",
        help="Path to repos.yaml. Defaults to <cwd>/repos.yaml.",
    )
    parser.add_argument(
        "--policies", default=None, metavar="DIR",
        help="Path to policies/ directory. Currently unused; reserved "
             "for D3 (failure-streak pause).",
    )
    parser.add_argument(
        "--max-concurrent", type=int, default=None, dest="max_concurrent",
        metavar="N",
        help="Global cap on dispatches per tick across all repos. "
             "Per-repo cap (repos.yaml#max_concurrent) still applies.",
    )
    parser.add_argument(
        "--log-level", default="INFO", dest="log_level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Log level (default: INFO).",
    )

    args = parser.parse_args(argv)
    _setup_logging(args.log_level)

    if not subprocess.run(["which", "grava"],
                          capture_output=True).returncode == 0:
        log.error("grava not on PATH — daemon cannot scan repos")
        return 1

    repos_yaml, state_dir = _resolve_paths(args)
    try:
        repos = _load_repos(repos_yaml)
    except FileNotFoundError as e:
        log.error("%s", e)
        return 1
    except yaml.YAMLError as e:
        log.error("repos.yaml malformed: %s", e)
        return 1

    if not repos:
        log.info("repos.yaml has 0 entries; nothing to do")
        return 0

    log.info("loaded %d repo(s) from %s: %s",
             len(repos), repos_yaml, ", ".join(repos))

    shutdown = _Shutdown()
    signal.signal(signal.SIGINT, shutdown.request)
    signal.signal(signal.SIGTERM, shutdown.request)

    backlog_interval = _min_poll_interval(repos)
    started_at = int(time.time())
    tick_count = 0
    pr_tick_count = 0
    pr_watcher = PRWatcher()
    # Both tickers fire immediately on startup (next_due = 0). After
    # that they advance by their own interval. The min(next_due) is
    # what the main loop waits for.
    backlog_next_due = 0.0
    prwatcher_next_due = 0.0
    last_backlog_result: TickResult | None = None
    last_pr_summary: dict | None = None

    while True:
        now = time.time()

        # ── backlog ticker (D1) ──
        if now >= backlog_next_due:
            tick_count += 1
            log.info("backlog tick %d start (%d repos)", tick_count, len(repos))
            last_backlog_result = _tick(repos)
            log.info(
                "backlog tick %d done: dispatched=%d skipped_capacity=%d "
                "skipped_blocked=%d paused=%d errors=%d",
                tick_count, last_backlog_result.dispatches,
                last_backlog_result.skipped_capacity,
                last_backlog_result.skipped_blocked,
                last_backlog_result.repos_paused,
                len(last_backlog_result.errors),
            )
            backlog_next_due = now + backlog_interval

        # ── pr-lifecycle ticker (D6) ──
        if now >= prwatcher_next_due:
            pr_tick_count += 1
            log.info("pr-watcher tick %d start (%d repos)",
                     pr_tick_count, len(repos))
            pr_events = 0
            pr_repos_scanned = 0
            for name, cfg in repos.items():
                if not cfg.path.is_dir():
                    continue
                if _is_paused(cfg.path):
                    continue
                report = pr_watcher.tick(cfg.path)
                pr_events += len(report.events)
                pr_repos_scanned += 1
            last_pr_summary = {
                "tick": pr_tick_count,
                "repos_scanned": pr_repos_scanned,
                "events": pr_events,
                "at": int(now),
            }
            log.info(
                "pr-watcher tick %d done: repos=%d events=%d",
                pr_tick_count, pr_repos_scanned, pr_events,
            )
            prwatcher_next_due = now + PR_WATCHER_INTERVAL

        # ── persist state ──
        _write_state(state_dir, {
            "started_at": started_at,
            "last_tick_at": int(now),
            "tick_count": tick_count,
            "pr_tick_count": pr_tick_count,
            "repos": list(repos),
            "last_tick": {
                "polled": last_backlog_result.repos_polled if last_backlog_result else 0,
                "paused": last_backlog_result.repos_paused if last_backlog_result else 0,
                "dispatches": last_backlog_result.dispatches if last_backlog_result else 0,
                "skipped_capacity": last_backlog_result.skipped_capacity if last_backlog_result else 0,
                "skipped_blocked": last_backlog_result.skipped_blocked if last_backlog_result else 0,
                "errors": last_backlog_result.errors if last_backlog_result else [],
            },
            "last_pr_tick": last_pr_summary or {},
        })

        if args.once or shutdown.stop:
            log.info("exiting (once=%s shutdown=%s)",
                     args.once, shutdown.stop)
            return 0

        # Sleep until the next ticker is due. Chunked in 1s slices so
        # SIGINT is responsive even with a 300s pr-watcher ticker.
        sleep_seconds = max(1, int(min(backlog_next_due, prwatcher_next_due) - now))
        slept = 0
        while slept < sleep_seconds and not shutdown.stop:
            time.sleep(min(1, sleep_seconds - slept))
            slept += 1
        if shutdown.stop:
            return 0


if __name__ == "__main__":
    sys.exit(main())
