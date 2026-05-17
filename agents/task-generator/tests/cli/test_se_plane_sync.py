"""Wiring tests for `se plane-sync` — confirms the subparser routes to
agents/task-generator/cli/grava_plane_sync.py without touching Plane or DB.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# tests/cli/test_se_plane_sync.py → parents[4] = repo root
REPO_ROOT = Path(__file__).resolve().parents[4]
SE = REPO_ROOT / "cli" / "se"


def test_se_executable_exists() -> None:
    assert SE.exists(), f"se CLI not found at {SE}"


def test_se_plane_sync_help_works() -> None:
    r = subprocess.run(
        [sys.executable, str(SE), "plane-sync", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert r.returncode == 0, r.stderr
    assert "--project-id" in r.stdout
    assert "--grava-repo" in r.stdout
    assert "issue_id" in r.stdout


def test_se_plane_sync_listed_in_root_help() -> None:
    r = subprocess.run(
        [sys.executable, str(SE), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert r.returncode == 0, r.stderr
    assert "plane-sync" in r.stdout


def test_se_plane_sync_missing_required_fails() -> None:
    r = subprocess.run(
        [sys.executable, str(SE), "plane-sync"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert r.returncode != 0
    combined = r.stderr + r.stdout
    assert "--project-id" in combined or "--grava-repo" in combined


def test_se_plane_sync_help_lists_direction() -> None:
    r = subprocess.run(
        [sys.executable, str(SE), "plane-sync", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert r.returncode == 0
    assert "--direction" in r.stdout
    assert "push" in r.stdout
    assert "pull" in r.stdout
    assert "both" in r.stdout


def test_se_plane_sync_default_direction_is_pull() -> None:
    """`se plane-sync` (operator UX) defaults to pull."""
    r = subprocess.run(
        [sys.executable, str(SE), "plane-sync", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert r.returncode == 0
    # Help text must call out pull as the default; defensive against future drift.
    assert "pull (default)" in r.stdout.lower() or "default: pull" in r.stdout.lower() \
        or "default='pull'" in r.stdout.lower()


def test_se_plane_sync_rejects_invalid_direction() -> None:
    r = subprocess.run(
        [
            sys.executable, str(SE), "plane-sync",
            "--project-id", "x", "--grava-repo", "/tmp",
            "--direction", "sideways",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert r.returncode != 0
    assert "sideways" in r.stderr or "invalid choice" in r.stderr
