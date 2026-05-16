"""Tests for cli/pick_ready.py — per-team backlog probe."""

from __future__ import annotations

import json
import sys

import pytest

import pick_ready
from conftest import FakeCompleted, grava_show_payload


def _run(monkeypatch, capsys, argv: list[str]) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "argv", ["pick_ready.py", *argv])
    try:
        rc = pick_ready.main() or 0
    except SystemExit as exc:
        rc = int(exc.code or 0)
    out, err = capsys.readouterr()
    return rc, out, err


def _ready(recorder, items: list[dict], returncode: int = 0):
    recorder.register(
        "grava", "ready", returncode=returncode, stdout=json.dumps(items)
    )


def _list(recorder, items: list[dict], returncode: int = 0):
    recorder.register(
        "grava", "list", returncode=returncode, stdout=json.dumps(items)
    )


def test_picks_bug_for_fix_bug_team(recorder, wisps, monkeypatch, capsys):
    _ready(recorder, [{"Node": {"ID": "grava-100", "Type": "bug", "Title": "x"}}])
    rc, out, _ = _run(monkeypatch, capsys, ["--team", "fix-bug"])
    assert rc == 0
    result = json.loads(out)
    assert result == [{"id": "grava-100", "title": "x", "type": "bug"}]


def test_skips_wrong_type(recorder, wisps, monkeypatch, capsys):
    _ready(
        recorder,
        [
            {"Node": {"ID": "grava-200", "Type": "task", "Title": "t"}},
            {"Node": {"ID": "grava-201", "Type": "bug", "Title": "b"}},
        ],
    )
    rc, out, _ = _run(monkeypatch, capsys, ["--team", "fix-bug"])
    assert rc == 0
    assert json.loads(out) == [{"id": "grava-201", "title": "b", "type": "bug"}]


def test_terminal_phase_unavailable(recorder, wisps, monkeypatch, capsys):
    _ready(recorder, [{"Node": {"ID": "grava-300", "Type": "bug", "Title": "x"}}])
    wisps.write("grava-300", "pipeline_phase", "pr_created")  # in flight
    rc, out, _ = _run(monkeypatch, capsys, ["--team", "fix-bug"])
    assert rc == 0
    assert json.loads(out) == []


def test_qa_team_uses_label_filter(recorder, wisps, monkeypatch, capsys):
    _list(recorder, [{"id": "grava-400", "title": "qa task", "type": "task"}])
    rc, out, _ = _run(monkeypatch, capsys, ["--team", "qa"])
    assert rc == 0
    assert json.loads(out)[0]["id"] == "grava-400"
    assert recorder.find_calls("grava", "list", "-L", "qa-ready")


def test_empty_backlog_returns_empty_list(recorder, wisps, monkeypatch, capsys):
    _ready(recorder, [])
    rc, out, _ = _run(monkeypatch, capsys, ["--team", "epic-task"])
    assert rc == 0
    assert json.loads(out) == []


def test_grava_failure_exit_1(recorder, monkeypatch, capsys):
    recorder.register("grava", "ready", returncode=1, stderr="db locked")
    rc, _, err = _run(monkeypatch, capsys, ["--team", "fix-bug"])
    assert rc == 1
    assert "db locked" in err


def test_task_generator_requires_tg_src_label(recorder, wisps, monkeypatch, capsys):
    # ready returns an epic without tg:src — show call returns no label.
    _ready(recorder, [{"Node": {"ID": "grava-500", "Type": "epic", "Title": "e"}}])
    recorder.register(
        "grava", "show", returncode=0, stdout=grava_show_payload(
            issue_id="grava-500", issue_type="epic", labels=[]
        ),
    )
    rc, out, _ = _run(monkeypatch, capsys, ["--team", "task-generator"])
    assert rc == 0
    assert json.loads(out) == []


def test_task_generator_with_tg_src(recorder, wisps, monkeypatch, capsys):
    _ready(recorder, [{"Node": {"ID": "grava-501", "Type": "epic", "Title": "e"}}])
    recorder.register(
        "grava", "show", returncode=0, stdout=grava_show_payload(
            issue_id="grava-501",
            issue_type="epic",
            labels=["tg:src:page-abc"],
        ),
    )
    rc, out, _ = _run(monkeypatch, capsys, ["--team", "task-generator"])
    assert rc == 0
    assert json.loads(out)[0]["id"] == "grava-501"


def test_limit_caps_results(recorder, wisps, monkeypatch, capsys):
    _ready(
        recorder,
        [
            {"Node": {"ID": f"grava-{i}", "Type": "bug", "Title": "x"}}
            for i in range(5)
        ],
    )
    rc, out, _ = _run(monkeypatch, capsys, ["--team", "fix-bug", "--limit", "2"])
    assert rc == 0
    assert len(json.loads(out)) == 2
