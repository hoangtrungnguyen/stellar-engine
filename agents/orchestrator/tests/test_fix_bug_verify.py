"""Tests for cli/fix_bug_verify.py — Phase 2 self-verify."""

from __future__ import annotations

import json
import sys

import pytest

import fix_bug_verify


def _run(monkeypatch, capsys, argv: list[str]) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "argv", ["fix_bug_verify.py", *argv])
    try:
        rc = fix_bug_verify.main() or 0
    except SystemExit as exc:
        rc = int(exc.code or 0)
    out, err = capsys.readouterr()
    return rc, out, err


@pytest.fixture
def worktree(tmp_path):
    """Provide a target repo with a real .worktree/<id>/ so verify doesn't bail."""
    wt = tmp_path / ".worktree" / "grava-001"
    wt.mkdir(parents=True)
    return tmp_path


def test_skip_verify_passes(recorder, wisps, monkeypatch, capsys, tmp_path):
    rc, out, _ = _run(
        monkeypatch,
        capsys,
        ["grava-001", "--target-repo", str(tmp_path), "--skip-verify"],
    )
    assert rc == 0
    payload = json.loads(out.splitlines()[-1])
    assert payload["verdict"] == "pass"
    assert wisps.read("grava-001", "self_verify_result") == "pass"
    assert wisps.read("grava-001", "pipeline_phase") == "coding_complete"


def test_all_checks_pass(recorder, wisps, monkeypatch, capsys, worktree):
    # Pretend golangci-lint isn't installed → skipped gracefully.
    monkeypatch.setattr(
        fix_bug_verify.shutil, "which",
        lambda name: "/usr/bin/" + name if name != "golangci-lint" else None,
    )
    # go test + go build both succeed.
    recorder.register("go", "test", returncode=0, stdout="ok")
    recorder.register("go", "build", returncode=0, stdout="")
    rc, out, _ = _run(
        monkeypatch, capsys, ["grava-001", "--target-repo", str(worktree)]
    )
    assert rc == 0
    assert json.loads(out.splitlines()[-1])["verdict"] == "pass"


def test_fail_first_attempt_returns_5(recorder, wisps, monkeypatch, capsys, worktree):
    monkeypatch.setattr(fix_bug_verify.shutil, "which", lambda _: None)
    recorder.register("go", "test", returncode=1, stdout="FAIL pkg/foo")
    recorder.register("go", "build", returncode=0, stdout="")
    rc, _, err = _run(
        monkeypatch, capsys, ["grava-001", "--target-repo", str(worktree)]
    )
    assert rc == 5
    assert "attempt 1/2" in err
    assert wisps.read("grava-001", "self_verify_result") == "fail"


def test_max_retries_exceeded_returns_2(
    recorder, wisps, monkeypatch, capsys, worktree
):
    monkeypatch.setattr(fix_bug_verify.shutil, "which", lambda _: None)
    recorder.register("go", "test", returncode=1, stdout="FAIL")
    recorder.register("go", "build", returncode=0)

    # Run 3 attempts; expect 5, 5, 2 (labels `needs-human` at attempt 3).
    for expected_rc in (5, 5, 2):
        capsys.readouterr()  # drain
        rc, _, _ = _run(
            monkeypatch, capsys, ["grava-001", "--target-repo", str(worktree)]
        )
        assert rc == expected_rc

    assert recorder.find_calls("grava", "label", "grava-001", "--add", "needs-human")


def test_missing_worktree_returns_2(recorder, monkeypatch, capsys, tmp_path):
    rc, _, err = _run(
        monkeypatch, capsys, ["grava-001", "--target-repo", str(tmp_path)]
    )
    assert rc == 2
    assert "worktree not found" in err
