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

DEFAULT_POLL_INTERVAL = 60          # seconds; matches repos.yaml default
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


def _grava_list_open(repo: Path) -> list[dict]:
    """Return all open issues in `repo` as a list of dicts."""
    r = subprocess.run(
        ["grava", "list", "--status", "open", "--json"],
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
    # grava list emits either a bare array or {"issues": [...]}; handle both.
    if isinstance(data, dict):
        data = data.get("issues") or data.get("Issues") or []
    return data if isinstance(data, list) else []


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
    """Single-pass scan of open issues: returns {team: in_flight_count}.

    An issue is in-flight when `pipeline_phase` wisp is set AND not in
    {"", "complete", "failed"}, AND has a `team` wisp.

    Two wisp reads per open issue. This is the obvious O(N) approach
    the daemon-plan flags for benching — fine for D1, optimise in a
    later phase if it stings.
    """
    counts: dict[str, int] = {team: 0 for team in TEAMS}
    for it in _grava_list_open(repo):
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

    sleep_seconds = _min_poll_interval(repos)
    started_at = int(time.time())
    tick_count = 0

    while True:
        tick_count += 1
        log.info("tick %d start (%d repos)", tick_count, len(repos))
        result = _tick(repos)
        log.info(
            "tick %d done: dispatched=%d skipped_capacity=%d paused=%d errors=%d",
            tick_count, result.dispatches, result.skipped_capacity,
            result.repos_paused, len(result.errors),
        )
        _write_state(state_dir, {
            "started_at": started_at,
            "last_tick_at": result.ts,
            "tick_count": tick_count,
            "repos": list(repos),
            "last_tick": {
                "polled": result.repos_polled,
                "paused": result.repos_paused,
                "dispatches": result.dispatches,
                "skipped_capacity": result.skipped_capacity,
                "errors": result.errors,
            },
        })

        if args.once or shutdown.stop:
            log.info("exiting (once=%s shutdown=%s)",
                     args.once, shutdown.stop)
            return 0

        # Sleep in small chunks so SIGINT is responsive.
        slept = 0
        while slept < sleep_seconds and not shutdown.stop:
            time.sleep(min(1, sleep_seconds - slept))
            slept += 1
        if shutdown.stop:
            return 0


if __name__ == "__main__":
    sys.exit(main())
