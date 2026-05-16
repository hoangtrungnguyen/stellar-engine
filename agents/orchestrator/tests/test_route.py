"""Tests for cli/route.py — type/label → team routing."""

from __future__ import annotations

import json
import sys

import pytest

import route
from conftest import grava_show_payload


def _run(monkeypatch, capsys, argv: list[str]) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "argv", ["route.py", *argv])
    try:
        rc = route.main() or 0
    except SystemExit as exc:
        rc = int(exc.code or 0)
    out, err = capsys.readouterr()
    return rc, out, err


def _show(recorder, payload: str, returncode: int = 0):
    recorder.register("grava", "show", returncode=returncode, stdout=payload)


@pytest.mark.parametrize(
    "issue_type, expected_team",
    [
        ("bug", "fix-bug"),
        ("task", "epic-task"),
        ("story", "epic-task"),
        ("subtask", "epic-task"),
        ("epic", "task-generator"),
    ],
)
def test_route_by_type(recorder, monkeypatch, capsys, issue_type, expected_team):
    _show(recorder, grava_show_payload(issue_id="grava-001", issue_type=issue_type))
    rc, out, _ = _run(monkeypatch, capsys, ["grava-001"])
    assert rc == 0
    blob = json.loads(out)
    assert blob["team"] == expected_team
    assert blob["type"] == issue_type
    assert blob["id"] == "grava-001"


def test_qa_ready_label_overrides_type(recorder, monkeypatch, capsys):
    """Strategy D7: `qa-ready` label routes to qa even if type is `bug`."""
    _show(
        recorder,
        grava_show_payload(
            issue_id="grava-002", issue_type="bug", labels=["qa-ready"]
        ),
    )
    rc, out, _ = _run(monkeypatch, capsys, ["grava-002"])
    assert rc == 0
    assert json.loads(out)["team"] == "qa"


def test_unroutable_type_exit_1(recorder, monkeypatch, capsys):
    _show(recorder, grava_show_payload(issue_id="grava-003", issue_type="spike"))
    rc, _, err = _run(monkeypatch, capsys, ["grava-003"])
    assert rc == 1
    assert "unroutable" in err.lower()
    assert "spike" in err


def test_grava_not_found_exit_1(recorder, monkeypatch, capsys):
    recorder.register("grava", "show", returncode=1, stderr="issue not found")
    rc, _, err = _run(monkeypatch, capsys, ["missing-id"])
    assert rc == 1
    assert "not found" in err.lower()


def test_grava_failure_exit_2(recorder, monkeypatch, capsys):
    recorder.register("grava", "show", returncode=1, stderr="db locked")
    rc, _, err = _run(monkeypatch, capsys, ["any-id"])
    assert rc == 2
    assert "db locked" in err


def test_route_writes_team_wisp(recorder, wisps, monkeypatch, capsys):
    _show(recorder, grava_show_payload(issue_id="grava-004", issue_type="bug"))
    rc, _, _ = _run(monkeypatch, capsys, ["grava-004"])
    assert rc == 0
    assert wisps.read("grava-004", "team") == "fix-bug"


def test_bad_json_exit_2(recorder, monkeypatch, capsys):
    recorder.register("grava", "show", returncode=0, stdout="not json at all")
    rc, _, err = _run(monkeypatch, capsys, ["grava-005"])
    assert rc == 2
    assert "bad JSON" in err
