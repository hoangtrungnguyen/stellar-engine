#!/usr/bin/env python3
"""
`se orchestrator run` — long-running fleet daemon.

This is the **Phase D0 scaffold** described in `docs/orchestrator/daemon-plan.md`.
It establishes the CLI surface (subcommand, flags, exit codes) without any
behaviour — the tick loop lands in D1. Until then, every invocation prints
a one-line stub message and exits 0.

Usage:
    python3 daemon.py            # would start the daemon loop (stub)
    python3 daemon.py --once     # would run a single tick + exit (stub)
    python3 daemon.py --help

Exit codes:
    0 = stub completed (every call, until D1 lands)
    2 = argparse error

The flags accepted here MUST stay forward-compatible with D1:
    --once, --repos, --policies, --max-concurrent, --log-level
Each is currently a no-op; D1 wires them to the real loop without changing
the surface, so `se orchestrator run --once` keeps the same shape from D0
through D6 (pr-lifecycle ticker — see [[pr-watcher-redesign]] in memory).

DO NOT add behaviour to this file until D1. The whole point of D0 is to
ship the subcommand wiring in isolation so `cli/se` and `agents/orchestrator/
AGENT.md` can reference `se orchestrator run` without lying about what
exists yet.
"""
import argparse
import sys


STUB_MESSAGE = (
    "daemon: not implemented (D0 scaffold). "
    "Phases D1 (tick loop) through D6 (pr-lifecycle ticker) land later — "
    "see docs/orchestrator/daemon-plan.md."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="se orchestrator run",
        description=(
            "Continuous-loop fleet daemon for stellar-engine. "
            "Polls repos.yaml, dispatches ready issues to teams, and "
            "(from Phase D6) folds in the PR-merge watcher. Currently a "
            "D0 stub — every invocation exits 0 without acting."
        ),
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run a single tick then exit. Will be honoured from D1; "
             "currently a no-op (the stub already exits after one print).",
    )
    parser.add_argument(
        "--repos", default=None, metavar="PATH",
        help="Path to repos.yaml. Defaults to <cwd>/repos.yaml when D1 "
             "lands; currently ignored.",
    )
    parser.add_argument(
        "--policies", default=None, metavar="DIR",
        help="Path to policies/ directory. Defaults to <cwd>/policies "
             "when D1 lands; currently ignored.",
    )
    parser.add_argument(
        "--max-concurrent", type=int, default=None, metavar="N",
        help="Global cap on in-flight pipelines across all repos. "
             "Per-repo cap still applies (repos.yaml#max_concurrent). "
             "Currently ignored.",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Log level (default: INFO). Currently ignored.",
    )

    args = parser.parse_args(argv)
    # `args` is intentionally unused — D0 only verifies the surface parses.
    del args

    print(STUB_MESSAGE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
