"""Tests for cli/doctor.py — environment health checks."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

import doctor


def test_check_stellar_engine_home_unset(monkeypatch):
    monkeypatch.delenv("STELLAR_ENGINE_HOME", raising=False)
    c = doctor.check_stellar_engine_home()
    assert c.status == "error"
    assert "unset" in c.detail


def test_check_stellar_engine_home_bad_path(monkeypatch, tmp_path):
    monkeypatch.setenv("STELLAR_ENGINE_HOME", str(tmp_path / "missing"))
    c = doctor.check_stellar_engine_home()
    assert c.status == "error"
    assert "does not exist" in c.detail


def test_check_stellar_engine_home_missing_sync_script(monkeypatch, tmp_path):
    monkeypatch.setenv("STELLAR_ENGINE_HOME", str(tmp_path))
    c = doctor.check_stellar_engine_home()
    assert c.status == "error"
    assert "grava_plane_sync.py" in c.detail


def test_check_stellar_engine_home_ok(monkeypatch, tmp_path):
    sync = tmp_path / "agents" / "task-generator" / "cli" / "grava_plane_sync.py"
    sync.parent.mkdir(parents=True)
    sync.write_text("# dummy")
    monkeypatch.setenv("STELLAR_ENGINE_HOME", str(tmp_path))
    c = doctor.check_stellar_engine_home()
    assert c.status == "ok"


def test_check_target_repo_missing(tmp_path):
    out = doctor.check_target_repo(tmp_path / "missing")
    assert out[0].status == "error"


def test_check_target_repo_no_grava(tmp_path):
    out = doctor.check_target_repo(tmp_path)
    statuses = {c.name: c.status for c in out}
    assert statuses["target repo"] == "ok"
    assert statuses["target repo: .grava/"] == "error"


def test_check_target_repo_with_grava(tmp_path):
    (tmp_path / ".grava").mkdir()
    out = doctor.check_target_repo(tmp_path)
    statuses = {c.name: c.status for c in out}
    assert statuses["target repo"] == "ok"
    assert statuses["target repo: .grava/"] == "ok"


def test_check_sync_failures_no_log(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "SYNC_FAILURE_LOG", tmp_path / "errors.jsonl")
    c = doctor.check_sync_failures()
    assert c.status == "ok"
    assert "no failure log" in c.detail


def test_check_sync_failures_recent_entry(monkeypatch, tmp_path):
    log = tmp_path / "errors.jsonl"
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    log.write_text(
        json.dumps({
            "ts": now,
            "project_id": "p",
            "issue_id": "grava-1",
            "gate": "plane_api",
            "exit_code": 3,
            "detail": "503",
        }) + "\n"
    )
    monkeypatch.setattr(doctor, "SYNC_FAILURE_LOG", log)
    c = doctor.check_sync_failures()
    assert c.status == "warn"
    assert "plane_api=1" in c.detail


def test_check_sync_failures_old_entry_ignored(monkeypatch, tmp_path):
    log = tmp_path / "errors.jsonl"
    # Year-old timestamp.
    log.write_text(
        json.dumps({
            "ts": "2025-01-01T00:00:00Z",
            "project_id": "p",
            "issue_id": "grava-1",
            "gate": "plane_api",
            "exit_code": 3,
            "detail": "503",
        }) + "\n"
    )
    monkeypatch.setattr(doctor, "SYNC_FAILURE_LOG", log)
    c = doctor.check_sync_failures()
    assert c.status == "ok"


def test_check_sync_failures_malformed_line_skipped(monkeypatch, tmp_path):
    log = tmp_path / "errors.jsonl"
    log.write_text("not json\n{\"bad\": ts}\n")
    monkeypatch.setattr(doctor, "SYNC_FAILURE_LOG", log)
    c = doctor.check_sync_failures()
    # Malformed lines silently skipped; treated as no failures.
    assert c.status == "ok"


def test_render_json(tmp_path):
    checks = [doctor.Check("x", "ok", "ok detail")]
    out = doctor.render(checks, as_json=True)
    parsed = json.loads(out)
    assert parsed[0]["name"] == "x"
    assert parsed[0]["status"] == "ok"


def test_main_exit_code_aggregates(monkeypatch, tmp_path, capsys):
    """Force one error → exit 1."""
    monkeypatch.delenv("STELLAR_ENGINE_HOME", raising=False)
    monkeypatch.setenv("PLANE_API_TOKEN", "t")
    monkeypatch.setenv("PLANE_WORKSPACE", "w")
    (tmp_path / ".grava").mkdir()
    monkeypatch.setattr(doctor, "SYNC_FAILURE_LOG", tmp_path / "absent.jsonl")
    monkeypatch.setattr(sys, "argv", ["doctor.py", "--target-repo", str(tmp_path)])
    rc = doctor.main()
    capsys.readouterr()
    # STELLAR_ENGINE_HOME unset → error → exit 1.
    assert rc == 1
