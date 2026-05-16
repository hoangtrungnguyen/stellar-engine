"""Tests for cli/fix_bug_claim.py — Phase 0 claim."""

from __future__ import annotations

import json
import sys

import pytest

import fix_bug_claim
from conftest import grava_show_payload


def _run(monkeypatch, capsys, argv: list[str]) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "argv", ["fix_bug_claim.py", *argv])
    try:
        rc = fix_bug_claim.main() or 0
    except SystemExit as exc:
        rc = int(exc.code or 0)
    out, err = capsys.readouterr()
    return rc, out, err


def _show(recorder, payload: str, returncode: int = 0):
    recorder.register("grava", "show", returncode=returncode, stdout=payload)


def test_claims_bug_writes_wisps(recorder, wisps, monkeypatch, capsys):
    _show(recorder, grava_show_payload(issue_id="grava-bug-1", issue_type="bug"))
    recorder.register("grava", "claim", returncode=0)
    rc, out, _ = _run(monkeypatch, capsys, ["grava-bug-1"])
    assert rc == 0
    payload = json.loads(out.splitlines()[-1])
    assert payload["id"] == "grava-bug-1"
    assert payload["worktree"].endswith(".worktree/grava-bug-1")
    assert payload["branch"] == "grava/grava-bug-1"
    assert wisps.read("grava-bug-1", "team") == "fix-bug"
    assert wisps.read("grava-bug-1", "pipeline_phase") == "claimed"
    assert wisps.read("grava-bug-1", "orchestrator_heartbeat")


def test_rejects_non_bug_type(recorder, wisps, monkeypatch, capsys):
    _show(recorder, grava_show_payload(issue_id="grava-task-1", issue_type="task"))
    rc, _, err = _run(monkeypatch, capsys, ["grava-task-1"])
    assert rc == 1
    assert "not 'bug'" in err
    # Must NOT call grava claim on wrong type.
    assert not recorder.find_calls("grava", "claim")


def test_issue_not_found(recorder, monkeypatch, capsys):
    recorder.register("grava", "show", returncode=1, stderr="not found")
    rc, _, err = _run(monkeypatch, capsys, ["missing"])
    assert rc == 1
    assert "not found" in err.lower()


def test_idempotent_when_already_claimed(recorder, wisps, monkeypatch, capsys):
    _show(recorder, grava_show_payload(issue_id="grava-bug-2", issue_type="bug"))
    wisps.write("grava-bug-2", "pipeline_phase", "claimed")
    rc, out, _ = _run(monkeypatch, capsys, ["grava-bug-2"])
    assert rc == 0
    payload = json.loads(out.splitlines()[-1])
    assert payload.get("idempotent") is True
    # Must NOT re-claim.
    assert not recorder.find_calls("grava", "claim")
    # Heartbeat refreshed.
    assert wisps.read("grava-bug-2", "orchestrator_heartbeat")


def test_idempotent_at_pr_created(recorder, wisps, monkeypatch, capsys):
    _show(recorder, grava_show_payload(issue_id="grava-bug-3", issue_type="bug"))
    wisps.write("grava-bug-3", "pipeline_phase", "pr_created")
    rc, out, _ = _run(monkeypatch, capsys, ["grava-bug-3"])
    assert rc == 0
    assert json.loads(out.splitlines()[-1]).get("idempotent") is True


def test_grava_claim_failure_exit_2(recorder, wisps, monkeypatch, capsys):
    _show(recorder, grava_show_payload(issue_id="grava-bug-4", issue_type="bug"))
    recorder.register(
        "grava", "claim", returncode=1, stderr="already claimed by other"
    )
    rc, _, err = _run(monkeypatch, capsys, ["grava-bug-4"])
    assert rc == 2
    assert "claim failed" in err.lower()


def test_bad_json_exit_1(recorder, monkeypatch, capsys):
    recorder.register("grava", "show", returncode=0, stdout="not-json")
    rc, _, err = _run(monkeypatch, capsys, ["grava-bug-5"])
    assert rc == 1
    assert "bad JSON" in err
