#!/usr/bin/env python3
"""
Stellar Engine doctor — verify the operator's environment can run the
orchestrator's sub-pipelines (fix-bug, QA, task-generator) and the v0
grava → Plane state sync.

Usage:
    python3 agents/orchestrator/cli/doctor.py [--target-repo <path>] [--json]

Exit codes:
    0 = all green
    1 = one or more errors
    2 = no errors, but warnings present

Closes G12 (STELLAR_ENGINE_HOME unset) and G9 (pr_merge_watcher cron not
wired) by surfacing both as concrete checks.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

SYNC_FAILURE_LOG = Path.home() / ".local" / "share" / "grava-plane-sync" / "errors.jsonl"

# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class Check:
    name: str
    status: str  # "ok" | "warn" | "error"
    detail: str = ""


# ──────────────────────────────────────────────────────────────────────────────


def check_binary(name: str, version_args: list[str] | None = None) -> Check:
    path = shutil.which(name)
    if not path:
        return Check(name, "error", f"{name} not on PATH")
    detail = path
    if version_args:
        try:
            r = subprocess.run([name, *version_args], capture_output=True, text=True, timeout=5)
            line = (r.stdout or r.stderr).strip().splitlines()
            if line:
                detail = f"{path}  ({line[0][:60]})"
        except Exception:  # noqa: BLE001
            pass
    return Check(name, "ok", detail)


def check_stellar_engine_home() -> Check:
    value = os.environ.get("STELLAR_ENGINE_HOME", "")
    if not value:
        return Check(
            "STELLAR_ENGINE_HOME",
            "error",
            "env var unset — grava agent hooks will fall back to a hard-coded path "
            "(/Users/trungnguyenhoang/IdeaProjects/stellar-engine). "
            "Set it: export STELLAR_ENGINE_HOME=/path/to/stellar-engine",
        )
    path = Path(value)
    if not path.is_dir():
        return Check("STELLAR_ENGINE_HOME", "error", f"path does not exist: {value}")
    sync = path / "agents" / "task-generator" / "cli" / "grava_plane_sync.py"
    if not sync.is_file():
        return Check(
            "STELLAR_ENGINE_HOME",
            "error",
            f"set, but {sync} not found — wrong checkout?",
        )
    return Check("STELLAR_ENGINE_HOME", "ok", value)


def _resolve_plane_config_path() -> Path:
    """Mirror of plane_client.resolve_plane_config_path so this module
    stays standalone (no agents/task-generator import).

    Priority: PLANE_CONFIG > PLANE_PROFILE > ~/.config/plane/config.json.
    """
    explicit = os.environ.get("PLANE_CONFIG", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    profile = os.environ.get("PLANE_PROFILE", "").strip()
    if profile:
        return Path.home() / ".config" / "plane" / f"{profile}.json"
    return Path.home() / ".config" / "plane" / "config.json"


def check_plane_creds() -> Check:
    env_token = os.environ.get("PLANE_API_TOKEN")
    env_ws = os.environ.get("PLANE_WORKSPACE")
    if env_token and env_ws:
        return Check(
            "Plane credentials", "ok",
            "via env vars (PLANE_API_TOKEN + PLANE_WORKSPACE)",
        )
    config_path = _resolve_plane_config_path()
    profile_hint = ""
    if "PLANE_PROFILE" in os.environ:
        profile_hint = f" (profile={os.environ['PLANE_PROFILE']})"
    elif "PLANE_CONFIG" in os.environ:
        profile_hint = " (PLANE_CONFIG override)"
    if not config_path.exists():
        return Check(
            "Plane credentials",
            "warn",
            f"{config_path} absent{profile_hint}. "
            f"Run bash setup.sh to configure, set PLANE_PROFILE=<name> for "
            f"~/.config/plane/<name>.json, or PLANE_CONFIG=<path> for an "
            f"arbitrary file. v0 grava→Plane sync will silently no-op until "
            f"configured.",
        )
    try:
        data = json.loads(config_path.read_text())
    except json.JSONDecodeError as exc:
        return Check(
            "Plane credentials", "error",
            f"config at {config_path} malformed: {exc}",
        )
    if data.get("token") and data.get("workspace"):
        return Check(
            "Plane credentials", "ok",
            f"workspace={data['workspace']}  via {config_path}{profile_hint}",
        )
    return Check(
        "Plane credentials", "error",
        f"{config_path} present but missing token/workspace",
    )


def check_cron(target_repo: Path) -> Check:
    watcher = "agents/orchestrator/scripts/pr_merge_watcher.sh"
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
    except FileNotFoundError:
        return Check(
            "pr_merge_watcher cron",
            "warn",
            "crontab not available on this system — install watcher loop manually",
        )
    if r.returncode != 0 and "no crontab" not in (r.stderr or "").lower():
        return Check("pr_merge_watcher cron", "warn", f"crontab -l failed: {r.stderr.strip()[:80]}")
    lines = (r.stdout or "").splitlines()
    has_watcher = any(watcher in line for line in lines if not line.lstrip().startswith("#"))
    if has_watcher:
        return Check("pr_merge_watcher cron", "ok", "installed")
    target_abs = target_repo.resolve()
    stellar_abs = Path(__file__).resolve().parents[3]
    return Check(
        "pr_merge_watcher cron",
        "warn",
        "no crontab entry found. Install:\n"
        f"        */5 * * * * cd {target_abs} && bash {stellar_abs}/{watcher}",
    )


def check_sync_failures(window_hours: int = 24) -> Check:
    """Warn if grava_plane_sync.py has logged failures in the last window."""
    if not SYNC_FAILURE_LOG.exists():
        return Check("grava→Plane sync failures", "ok", "no failure log yet")
    cutoff = time.time() - window_hours * 3600
    recent_by_gate: dict[str, int] = {}
    total = 0
    try:
        with SYNC_FAILURE_LOG.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts_str = rec.get("ts", "")
                try:
                    ts = time.mktime(time.strptime(ts_str, "%Y-%m-%dT%H:%M:%SZ"))
                except ValueError:
                    continue
                if ts < cutoff:
                    continue
                total += 1
                gate = rec.get("gate", "unknown")
                recent_by_gate[gate] = recent_by_gate.get(gate, 0) + 1
    except OSError as exc:
        return Check("grava→Plane sync failures", "warn", f"could not read log: {exc}")
    if not total:
        return Check(
            "grava→Plane sync failures",
            "ok",
            f"no failures in last {window_hours}h ({SYNC_FAILURE_LOG})",
        )
    breakdown = ", ".join(f"{g}={n}" for g, n in sorted(recent_by_gate.items()))
    return Check(
        "grava→Plane sync failures",
        "warn",
        f"{total} failure(s) in last {window_hours}h — {breakdown}\n"
        f"Log: {SYNC_FAILURE_LOG}",
    )


def check_target_repo(target_repo: Path) -> list[Check]:
    out: list[Check] = []
    if not target_repo.is_dir():
        out.append(Check("target repo", "error", f"path does not exist: {target_repo}"))
        return out
    out.append(Check("target repo", "ok", str(target_repo.resolve())))
    grava_dir = target_repo / ".grava"
    if grava_dir.is_dir():
        out.append(Check("target repo: .grava/", "ok", "grava initialised"))
    else:
        out.append(
            Check(
                "target repo: .grava/",
                "error",
                "directory missing — run `cd <repo> && grava init` first",
            )
        )
    return out


# ──────────────────────────────────────────────────────────────────────────────


def render(checks: list[Check], as_json: bool) -> str:
    if as_json:
        return json.dumps([c.__dict__ for c in checks], indent=2)
    lines = []
    icon = {"ok": "✓", "warn": "⚠", "error": "✗"}
    for c in checks:
        prefix = icon[c.status]
        lines.append(f"  {prefix}  {c.name}")
        if c.detail:
            for d in c.detail.splitlines():
                lines.append(f"      {d}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target-repo", type=Path, default=Path("."))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    checks: list[Check] = []

    # Tooling
    checks.append(check_binary("python3", ["--version"]))
    checks.append(check_binary("grava"))
    checks.append(check_binary("gh", ["--version"]))
    checks.append(check_binary("git", ["--version"]))

    # Environment
    checks.append(check_stellar_engine_home())
    checks.append(check_plane_creds())

    # Target repo
    checks.extend(check_target_repo(args.target_repo))

    # Watcher cron
    checks.append(check_cron(args.target_repo))

    # G11 — sync failure log
    checks.append(check_sync_failures())

    print(render(checks, args.json))

    errors = sum(1 for c in checks if c.status == "error")
    warnings = sum(1 for c in checks if c.status == "warn")
    if not args.json:
        print()
        if errors:
            print(f"  {errors} error(s), {warnings} warning(s). Fix errors before running pipelines.")
        elif warnings:
            print(f"  {warnings} warning(s). Stellar Engine operational with caveats.")
        else:
            print("  All green.")

    if errors:
        return 1
    if warnings:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
