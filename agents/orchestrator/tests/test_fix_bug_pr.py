"""Tests for cli/fix_bug_pr.py — Phase 3 PR creation."""

from __future__ import annotations

import json
import sys

import pytest

import fix_bug_pr
from conftest import grava_show_payload


def _run(monkeypatch, capsys, argv: list[str]) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "argv", ["fix_bug_pr.py", *argv])
    try:
        rc = fix_bug_pr.main() or 0
    except SystemExit as exc:
        rc = int(exc.code or 0)
    out, err = capsys.readouterr()
    return rc, out, err


@pytest.fixture
def ready_state(tmp_path, wisps):
    """Repo + worktree + wisps satisfying Phase 3 preconditions."""
    wt = tmp_path / ".worktree" / "grava-001"
    wt.mkdir(parents=True)
    wisps.write("grava-001", "pipeline_phase", "coding_complete")
    wisps.write("grava-001", "self_verify_result", "pass")
    return tmp_path


def test_happy_path(recorder, wisps, monkeypatch, capsys, ready_state):
    # grava show for PR title/desc.
    recorder.register(
        "grava", "show", returncode=0,
        stdout=grava_show_payload(issue_id="grava-001", title="Fix off-by-one"),
    )
    # git push succeeds.
    recorder.register("git", "push", returncode=0)
    # gh pr create returns a URL.
    recorder.register(
        "gh", "pr", "create",
        returncode=0,
        stdout="https://github.com/o/r/pull/42\n",
    )
    # gh pr view --json number
    recorder.register("gh", "pr", "view", returncode=0, stdout="42")
    rc, out, _ = _run(monkeypatch, capsys, ["grava-001", "--target-repo", str(ready_state)])
    assert rc == 0
    payload = json.loads(out.splitlines()[-1])
    assert payload["pr_url"] == "https://github.com/o/r/pull/42"
    assert payload["pr_number"] == "42"
    assert wisps.read("grava-001", "pipeline_phase") == "pr_created"
    assert wisps.read("grava-001", "pr_url") == "https://github.com/o/r/pull/42"


def test_precondition_unmet(recorder, wisps, monkeypatch, capsys, tmp_path):
    # No wisps set — preconditions fail.
    (tmp_path / ".worktree" / "grava-001").mkdir(parents=True)
    rc, _, err = _run(monkeypatch, capsys, ["grava-001", "--target-repo", str(tmp_path)])
    assert rc == 1
    assert "self-verify not passed" in err
    assert not recorder.find_calls("git", "push")
    assert not recorder.find_calls("gh", "pr", "create")


def test_idempotent_pr_already_created(recorder, wisps, monkeypatch, capsys, ready_state):
    wisps.write("grava-001", "pipeline_phase", "pr_created")
    wisps.write("grava-001", "pr_url", "https://github.com/o/r/pull/99")
    wisps.write("grava-001", "pr_number", "99")
    rc, out, _ = _run(monkeypatch, capsys, ["grava-001", "--target-repo", str(ready_state)])
    assert rc == 0
    payload = json.loads(out.splitlines()[-1])
    assert payload.get("idempotent") is True
    assert payload["pr_url"] == "https://github.com/o/r/pull/99"
    assert not recorder.find_calls("git", "push")
    assert not recorder.find_calls("gh", "pr", "create")


def test_git_push_failure_returns_2(recorder, wisps, monkeypatch, capsys, ready_state):
    recorder.register(
        "grava", "show", returncode=0,
        stdout=grava_show_payload(issue_id="grava-001"),
    )
    recorder.register("git", "push", returncode=1, stderr="rejected non-fast-forward")
    rc, _, err = _run(monkeypatch, capsys, ["grava-001", "--target-repo", str(ready_state)])
    assert rc == 2
    assert "push failed" in err
    assert not recorder.find_calls("gh", "pr", "create")


def test_gh_failure_returns_2(recorder, wisps, monkeypatch, capsys, ready_state):
    recorder.register(
        "grava", "show", returncode=0,
        stdout=grava_show_payload(issue_id="grava-001"),
    )
    recorder.register("git", "push", returncode=0)
    recorder.register(
        "gh", "pr", "create", returncode=1, stderr="gh auth status: not logged in"
    )
    rc, _, err = _run(monkeypatch, capsys, ["grava-001", "--target-repo", str(ready_state)])
    assert rc == 2
    assert "gh pr create failed" in err
